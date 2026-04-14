from datetime import datetime, timedelta, time
from typing import List, Dict, Optional
import models

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

def parse_time(t: str) -> time:
    h, m = t.split(":")
    return time(int(h), int(m))

def get_effective_working_hours(doctor: models.Doctor, dt: datetime, db) -> List[Dict]:
    from sqlalchemy.orm import Session
    target_date = dt.date()
    day_name = DAYS[target_date.weekday()]

    temp = db.query(models.ScheduleChange).filter(
        models.ScheduleChange.doctor_id == doctor.id,
        models.ScheduleChange.is_temporary == True,
        models.ScheduleChange.start_time <= dt,
        models.ScheduleChange.end_time >= dt,
    ).first()

    if temp:
        schedule = temp.new_working_hours
        return schedule.get(day_name, {}).get("periods", [])

    perm_changes = db.query(models.ScheduleChange).filter(
        models.ScheduleChange.doctor_id == doctor.id,
        models.ScheduleChange.is_temporary == False,
        models.ScheduleChange.start_time <= datetime.combine(target_date, time(0, 0)),
    ).order_by(models.ScheduleChange.start_time.desc()).first()

    if perm_changes:
        schedule = perm_changes.new_working_hours
        return schedule.get(day_name, {}).get("periods", [])

    return doctor.working_hours.get(day_name, {}).get("periods", [])

def is_within_working_hours(doctor: models.Doctor, start: datetime, end: datetime, db) -> bool:
    if start.date() != end.date():
        return False

    periods = get_effective_working_hours(doctor, start, db)
    if not periods:
        return False

    start_t = start.time()
    end_t = end.time()

    for period in periods:
        p_start = parse_time(period["start"])
        p_end = parse_time(period["end"])
        if p_start <= start_t and end_t <= p_end:
            return True
    return False

def has_conflicting_appointment(doctor_id: int, start: datetime, end: datetime, db, exclude_id: Optional[int] = None) -> bool:
    query = db.query(models.Appointment).filter(
        models.Appointment.doctor_id == doctor_id,
        models.Appointment.cancelled == False,
        models.Appointment.start_time < end,
        models.Appointment.end_time > start,
    )
    if exclude_id:
        query = query.filter(models.Appointment.id != exclude_id)
    return query.first() is not None
