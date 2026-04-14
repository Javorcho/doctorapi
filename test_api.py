import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta

from main import app
from database import get_db
from models import Base

TEST_DATABASE_URL = "sqlite:///./test_clinic.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

client = TestClient(app)

WORKING_HOURS = {
    "monday": {"periods": [{"start": "08:00", "end": "17:00"}]},
    "tuesday": {"periods": [{"start": "08:00", "end": "17:00"}]},
    "wednesday": {"periods": [{"start": "08:00", "end": "17:00"}]},
    "thursday": {"periods": [{"start": "08:00", "end": "17:00"}]},
    "friday": {"periods": [{"start": "08:00", "end": "17:00"}]},
    "saturday": {"periods": []},
    "sunday": {"periods": []},
}

def register_doctor(email="doc@test.com", password="pass123"):
    return client.post("/auth/register/doctor", json={
        "name": "Dr. Test",
        "email": email,
        "password": password,
        "address": "123 Main St",
        "working_hours": WORKING_HOURS,
    })

def login_doctor(email="doc@test.com", password="pass123"):
    r = client.post("/auth/login", json={"email": email, "password": password, "role": "doctor"})
    return r.json()["access_token"]

def register_patient(doctor_id, email="pat@test.com", password="pass123"):
    return client.post("/auth/register/patient", json={
        "name": "Patient Test",
        "email": email,
        "password": password,
        "phone": "0888123456",
        "doctor_id": doctor_id,
    })

def login_patient(email="pat@test.com", password="pass123"):
    r = client.post("/auth/login", json={"email": email, "password": password, "role": "patient"})
    return r.json()["access_token"]

def auth_header(token):
    return {"Authorization": f"Bearer {token}"}

def future_appointment(days_ahead=2, hour=10):
    now = datetime.utcnow()
    start = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    while start.weekday() >= 5:
        start += timedelta(days=1)
        end += timedelta(days=1)
    return start.isoformat(), end.isoformat()

class TestDoctorRegistration:
    def test_register_doctor_success(self):
        r = register_doctor()
        assert r.status_code == 200
        assert r.json()["email"] == "doc@test.com"

    def test_register_doctor_duplicate_email(self):
        register_doctor()
        r = register_doctor()
        assert r.status_code == 400

class TestPatientRegistration:
    def test_register_patient_success(self):
        doc = register_doctor().json()
        r = register_patient(doc["id"])
        assert r.status_code == 200
        assert r.json()["email"] == "pat@test.com"

    def test_register_patient_invalid_doctor(self):
        r = register_patient(9999)
        assert r.status_code == 404

    def test_register_patient_duplicate_email(self):
        doc = register_doctor().json()
        register_patient(doc["id"])
        r = register_patient(doc["id"])
        assert r.status_code == 400

class TestAuth:
    def test_login_doctor_success(self):
        register_doctor()
        r = client.post("/auth/login", json={"email": "doc@test.com", "password": "pass123", "role": "doctor"})
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_login_wrong_password(self):
        register_doctor()
        r = client.post("/auth/login", json={"email": "doc@test.com", "password": "wrong", "role": "doctor"})
        assert r.status_code == 401

    def test_protected_route_without_token(self):
        r = client.get("/appointments")
        assert r.status_code == 401

class TestAppointments:
    def setup_users(self):
        doc = register_doctor().json()
        register_patient(doc["id"])
        doc_token = login_doctor()
        pat_token = login_patient()
        return doc, doc_token, pat_token

    def test_create_appointment_success(self):
        doc, _, pat_token = self.setup_users()
        start, end = future_appointment()
        r = client.post("/appointments", json={"start_time": start, "end_time": end}, headers=auth_header(pat_token))
        assert r.status_code == 200
        assert r.json()["cancelled"] == False

    def test_create_appointment_too_soon(self):
        _, _, pat_token = self.setup_users()
        start = (datetime.utcnow() + timedelta(hours=12)).isoformat()
        end = (datetime.utcnow() + timedelta(hours=13)).isoformat()
        r = client.post("/appointments", json={"start_time": start, "end_time": end}, headers=auth_header(pat_token))
        assert r.status_code == 400

    def test_create_appointment_outside_hours(self):
        _, _, pat_token = self.setup_users()
        start = (datetime.utcnow() + timedelta(days=2)).replace(hour=20, minute=0, second=0, microsecond=0).isoformat()
        end = (datetime.utcnow() + timedelta(days=2)).replace(hour=21, minute=0, second=0, microsecond=0).isoformat()
        r = client.post("/appointments", json={"start_time": start, "end_time": end}, headers=auth_header(pat_token))
        assert r.status_code == 400

    def test_create_appointment_conflict(self):
        _, _, pat_token = self.setup_users()
        start, end = future_appointment()
        client.post("/appointments", json={"start_time": start, "end_time": end}, headers=auth_header(pat_token))
        r = client.post("/appointments", json={"start_time": start, "end_time": end}, headers=auth_header(pat_token))
        assert r.status_code == 400

    def test_doctor_cannot_create_appointment(self):
        _, doc_token, _ = self.setup_users()
        start, end = future_appointment()
        r = client.post("/appointments", json={"start_time": start, "end_time": end}, headers=auth_header(doc_token))
        assert r.status_code == 403

    def test_cancel_appointment_by_patient(self):
        _, _, pat_token = self.setup_users()
        start, end = future_appointment(days_ahead=3)
        appt = client.post("/appointments", json={"start_time": start, "end_time": end}, headers=auth_header(pat_token)).json()
        r = client.delete(f"/appointments/{appt['id']}", headers=auth_header(pat_token))
        assert r.status_code == 200

    def test_cancel_appointment_by_doctor(self):
        _, doc_token, pat_token = self.setup_users()
        start, end = future_appointment(days_ahead=3)
        appt = client.post("/appointments", json={"start_time": start, "end_time": end}, headers=auth_header(pat_token)).json()
        r = client.delete(f"/appointments/{appt['id']}", headers=auth_header(doc_token))
        assert r.status_code == 200

    def test_get_my_appointments(self):
        _, _, pat_token = self.setup_users()
        start, end = future_appointment()
        client.post("/appointments", json={"start_time": start, "end_time": end}, headers=auth_header(pat_token))
        r = client.get("/appointments", headers=auth_header(pat_token))
        assert r.status_code == 200
        assert len(r.json()) == 1

class TestScheduleChanges:
    def setup_doctor(self):
        register_doctor()
        return login_doctor()

    def test_add_temporary_schedule(self):
        token = self.setup_doctor()
        data = {
            "start_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=5)).isoformat(),
            "new_working_hours": WORKING_HOURS,
        }
        r = client.post("/doctors/schedule/temporary", json=data, headers=auth_header(token))
        assert r.status_code == 200

    def test_add_duplicate_temporary_schedule(self):
        token = self.setup_doctor()
        data = {
            "start_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=5)).isoformat(),
            "new_working_hours": WORKING_HOURS,
        }
        client.post("/doctors/schedule/temporary", json=data, headers=auth_header(token))
        r = client.post("/doctors/schedule/temporary", json=data, headers=auth_header(token))
        assert r.status_code == 400

    def test_remove_temporary_schedule(self):
        token = self.setup_doctor()
        data = {
            "start_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=5)).isoformat(),
            "new_working_hours": WORKING_HOURS,
        }
        client.post("/doctors/schedule/temporary", json=data, headers=auth_header(token))
        r = client.delete("/doctors/schedule/temporary", headers=auth_header(token))
        assert r.status_code == 200

    def test_add_permanent_schedule_too_soon(self):
        token = self.setup_doctor()
        data = {
            "effective_from": (datetime.utcnow() + timedelta(days=3)).isoformat(),
            "new_working_hours": WORKING_HOURS,
        }
        r = client.post("/doctors/schedule/permanent", json=data, headers=auth_header(token))
        assert r.status_code == 400

    def test_add_permanent_schedule_success(self):
        token = self.setup_doctor()
        data = {
            "effective_from": (datetime.utcnow() + timedelta(weeks=2)).isoformat(),
            "new_working_hours": WORKING_HOURS,
        }
        r = client.post("/doctors/schedule/permanent", json=data, headers=auth_header(token))
        assert r.status_code == 200
