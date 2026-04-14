from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from database import get_db
import models, schemas, auth, schedule as sched

router = APIRouter()

@router.post("/auth/register/doctor", tags=["Auth"])
def register_doctor(data: schemas.DoctorRegister, db: Session = Depends(get_db)):
    if db.query(models.Doctor).filter(models.Doctor.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    doctor = models.Doctor(
        name=data.name,
        email=data.email,
        password_hash=auth.hash_password(data.password),
        address=data.address,
        working_hours={k: v.model_dump() for k, v in data.working_hours.items()},
    )
    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    return {"id": doctor.id, "name": doctor.name, "email": doctor.email}

@router.post("/auth/register/patient", tags=["Auth"])
def register_patient(data: schemas.PatientRegister, db: Session = Depends(get_db)):
    if db.query(models.Patient).filter(models.Patient.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    doctor = db.query(models.Doctor).filter(models.Doctor.id == data.doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    patient = models.Patient(
        name=data.name,
        email=data.email,
        password_hash=auth.hash_password(data.password),
        phone=data.phone,
        doctor_id=data.doctor_id,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return {"id": patient.id, "name": patient.name, "email": patient.email}

@router.post("/auth/login", tags=["Auth"])
def login(data: schemas.LoginRequest, db: Session = Depends(get_db)):
    if data.role == "doctor":
        user = db.query(models.Doctor).filter(models.Doctor.email == data.email).first()
    elif data.role == "patient":
        user = db.query(models.Patient).filter(models.Patient.email == data.email).first()
    else:
        raise HTTPException(status_code=400, detail="Role must be 'doctor' or 'patient'")
    if not user or not auth.verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = auth.create_access_token({"sub": str(user.id), "role": data.role})
    return {"access_token": token, "token_type": "bearer"}

@router.post("/doctors/schedule/temporary", tags=["Doctors"])
def add_temporary_schedule(
    data: schemas.TemporaryScheduleChange,
    doctor: models.Doctor = Depends(auth.require_doctor),
    db: Session = Depends(get_db),
):
    existing = db.query(models.ScheduleChange).filter(
        models.ScheduleChange.doctor_id == doctor.id,
        models.ScheduleChange.is_temporary == True,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="A temporary schedule change already exists")
    change = models.ScheduleChange(
        doctor_id=doctor.id,
        is_temporary=True,
        start_time=data.start_time,
        end_time=data.end_time,
        new_working_hours={k: v.model_dump() for k, v in data.new_working_hours.items()},
    )
    db.add(change)
    db.commit()
    db.refresh(change)
    return change

@router.delete("/doctors/schedule/temporary", tags=["Doctors"])
def remove_temporary_schedule(
    doctor: models.Doctor = Depends(auth.require_doctor),
    db: Session = Depends(get_db),
):
    existing = db.query(models.ScheduleChange).filter(
        models.ScheduleChange.doctor_id == doctor.id,
        models.ScheduleChange.is_temporary == True,
    ).first()
    if not existing:
        raise HTTPException(status_code=404, detail="No temporary schedule change found")
    db.delete(existing)
    db.commit()
    return {"detail": "Temporary schedule change removed"}

@router.post("/doctors/schedule/permanent", tags=["Doctors"])
def add_permanent_schedule(
    data: schemas.PermanentScheduleChange,
    doctor: models.Doctor = Depends(auth.require_doctor),
    db: Session = Depends(get_db),
):
    if data.effective_from < datetime.utcnow() + timedelta(weeks=1):
        raise HTTPException(status_code=400, detail="Effective date must be at least 1 week in the future")
    change = models.ScheduleChange(
        doctor_id=doctor.id,
        is_temporary=False,
        start_time=data.effective_from,
        end_time=None,
        new_working_hours={k: v.model_dump() for k, v in data.new_working_hours.items()},
    )
    db.add(change)
    db.commit()
    db.refresh(change)
    return change

@router.post("/appointments", tags=["Appointments"])
def create_appointment(
    data: schemas.AppointmentCreate,
    current=Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    if current["role"] == "patient":
        patient = current["user"]
        doctor = db.query(models.Doctor).filter(models.Doctor.id == patient.doctor_id).first()
    else:
        raise HTTPException(status_code=403, detail="Only patients can create appointments")

    now = datetime.utcnow()
    if data.start_time <= now + timedelta(hours=24):
        raise HTTPException(status_code=400, detail="Appointment must be created at least 24 hours in advance")

    if not sched.is_within_working_hours(doctor, data.start_time, data.end_time, db):
        raise HTTPException(status_code=400, detail="Appointment is outside working hours")

    if sched.has_conflicting_appointment(doctor.id, data.start_time, data.end_time, db):
        raise HTTPException(status_code=400, detail="Time slot conflicts with another appointment")

    appointment = models.Appointment(
        start_time=data.start_time,
        end_time=data.end_time,
        patient_id=patient.id,
        doctor_id=doctor.id,
    )
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return appointment

@router.delete("/appointments/{appointment_id}", tags=["Appointments"])
def cancel_appointment(
    appointment_id: int,
    current=Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    appointment = db.query(models.Appointment).filter(models.Appointment.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    user = current["user"]
    role = current["role"]

    if role == "patient" and appointment.patient_id != user.id:
        raise HTTPException(status_code=403, detail="Not your appointment")
    if role == "doctor" and appointment.doctor_id != user.id:
        raise HTTPException(status_code=403, detail="Not your appointment")

    if appointment.cancelled:
        raise HTTPException(status_code=400, detail="Already cancelled")

    if appointment.start_time <= datetime.utcnow() + timedelta(hours=12):
        raise HTTPException(status_code=400, detail="Cannot cancel less than 12 hours before appointment")

    appointment.cancelled = True
    db.commit()
    return {"detail": "Appointment cancelled"}

@router.get("/appointments", tags=["Appointments"])
def get_my_appointments(
    current=Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    user = current["user"]
    role = current["role"]

    if role == "patient":
        appointments = db.query(models.Appointment).filter(models.Appointment.patient_id == user.id).all()
    else:
        appointments = db.query(models.Appointment).filter(models.Appointment.doctor_id == user.id).all()

    return appointments
