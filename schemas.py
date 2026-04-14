from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime

class WorkingPeriod(BaseModel):
    start: str
    end: str

class DaySchedule(BaseModel):
    periods: List[WorkingPeriod]

class DoctorRegister(BaseModel):
    name: str
    email: EmailStr
    password: str
    address: str
    working_hours: Dict[str, DaySchedule]

class PatientRegister(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: str
    doctor_id: int

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    role: str

class AppointmentCreate(BaseModel):
    start_time: datetime
    end_time: datetime

class AppointmentOut(BaseModel):
    id: int
    start_time: datetime
    end_time: datetime
    patient_id: int
    doctor_id: int
    cancelled: bool

    class Config:
        from_attributes = True

class TemporaryScheduleChange(BaseModel):
    start_time: datetime
    end_time: datetime
    new_working_hours: Dict[str, DaySchedule]

class PermanentScheduleChange(BaseModel):
    effective_from: datetime
    new_working_hours: Dict[str, DaySchedule]

class ScheduleChangeOut(BaseModel):
    id: int
    doctor_id: int
    is_temporary: bool
    start_time: datetime
    end_time: Optional[datetime]
    new_working_hours: Dict[str, Any]

    class Config:
        from_attributes = True
