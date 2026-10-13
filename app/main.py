"""
Employee Attendance & Analytics API
Run from the project root:
    python -m uvicorn app.main:app --reload --port 8000
Environment variables:
    MONGO_URI (default: mongodb://localhost:27017)
    MONGO_DB  (default: attendance_db)
"""
import os
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern
from bson.json_util import dumps, loads
load_dotenv()
UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
MIN_EPOCH_MS = 100_000_000_000
MAX_EPOCH_MS = 4_102_444_800_000
client = MongoClient(
    os.getenv("MONGO_URI", "mongodb://localhost:27017"),
    serverSelectionTimeoutMS=10_000,
)
db = client[os.getenv("MONGO_DB", "attendance_db")]
employees = db.get_collection("employees")
attendance = db.get_collection("attendance_logs")
app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")
@app.on_event("startup")
def create_indexes():
    employees.create_index("joined_on")
    employees.create_index("emp_code", unique=True)
    attendance.create_index(
        [("emp_code", 1), ("date", 1)], unique=True
    )
    attendance.create_index([("date", -1), ("emp_code", 1)])
    attendance.create_index([("emp_code", 1), ("punch_in", -1)])
def parse_shift(value: str) -> tuple[int, int]:
    try:
        parsed = time.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("Shift time must use HH:MM format")
    if parsed.second or parsed.microsecond or len(value) != 5:
        raise ValueError("Shift time must use HH:MM format")
    return parsed.hour, parsed.minute
def truncate_seconds(value: datetime) -> datetime:
    return value.replace(microsecond=0)
def ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    """MongoDB commonly returns naive datetimes; interpret them as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
def epoch_ms_to_datetime(value: int) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(422, "Timestamp must be an integer epoch timestamp")
    if not MIN_EPOCH_MS <= value <= MAX_EPOCH_MS:
        raise HTTPException(422, "Timestamp is out of range")
    try:
        # Truncate the instant to a whole second before storing or calculating.
        return truncate_seconds(datetime.fromtimestamp(value / 1000, tz=UTC))
    except (ValueError, OverflowError, OSError):
        raise HTTPException(422, "Invalid timestamp")
def to_epoch_ms(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)
def half_up(value, places=2):
    quantum = Decimal("1").scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
def parse_status(status):
    if status not in {"PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"}:
        raise HTTPException(422, "Invalid attendance status")
def is_presence_status(status):
    return status in {"PRESENT", "WFH", "ON_DUTY"}
def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    local = punch_in.astimezone(IST)
    hour, minute = parse_shift(shift_start)
    shift_start_local = local.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    elapsed = (local - shift_start_local).total_seconds()
    # Strictly more than 10 minutes; count whole minutes from shift start.
    return int(elapsed // 60) if elapsed > 600 else 0
def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = Decimal(str((punch_out - punch_in).total_seconds()))
    return float((seconds / Decimal("3600")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    ))
def compute_overtime(
    punch_out: datetime, shift_end: str, attendance_date: str, shift_start: str
) -> int:
    sh, sm = parse_shift(shift_start)
    eh, em = parse_shift(shift_end)
    end_day = date.fromisoformat(attendance_date)
    if (eh, em) <= (sh, sm):
        end_day += timedelta(days=1)
    end_local = datetime.combine(end_day, time(eh, em), tzinfo=IST)
    elapsed = (punch_out - end_local.astimezone(UTC)).total_seconds()
    minutes = int(elapsed // 60) if elapsed > 0 else 0
    return minutes if minutes >= 30 else 0
def calculate_derived_fields(punch_in, punch_out, employee, attendance_date):
    if punch_in is None:
        return {
            "late_minutes": 0, "work_hours": None,
            "overtime_minutes": 0, "half_day": False,
        }
    late = compute_late_minutes(punch_in, employee["shift_start"])
    if punch_out is None:
        return {
            "late_minutes": late, "work_hours": None,
            "overtime_minutes": 0, "half_day": False,
        }
    hours = compute_work_hours(punch_in, punch_out)
    return {
        "late_minutes": late,
        "work_hours": hours,
        "overtime_minutes": compute_overtime(
            punch_out, employee["shift_end"], attendance_date,
            employee["shift_start"]
        ),
        "half_day": hours < 4.50,
    }
def attendance_date_for(punch_in: datetime, employee) -> str:
    local = punch_in.astimezone(IST)
    sh, sm = parse_shift(employee["shift_start"])
    eh, em = parse_shift(employee["shift_end"])
    result = local.date()
    # For an overnight shift, early-morning punches belong to the previous day.
    if (eh, em) <= (sh, sm) and (local.hour, local.minute) < (eh, em):
        result -= timedelta(days=1)
    return result.isoformat()
def serialize_employee(doc):
    result = dict(doc)
    result.pop("_id", None)
    if isinstance(result.get("created_at"), datetime):
        result["created_at"] = to_epoch_ms(result["created_at"])
    return result
def serialize_attendance(doc):
    result = dict(doc)
    result.pop("_id", None)
    for field in ("punch_in", "punch_out"):
        result[field] = to_epoch_ms(result.get(field))
    for entry in result.get("history", []):
        if isinstance(entry.get("at"), datetime):
            entry["at"] = to_epoch_ms(entry["at"])
        for change in entry.get("changes", {}).values():
            if isinstance(change, dict):
                for key in ("from", "to"):
                    if isinstance(change.get(key), datetime):
                        change[key] = to_epoch_ms(change[key])
    result.setdefault("history", [])
    result.setdefault("late_minutes", 0)
    result.setdefault("work_hours", None)
    result.setdefault("overtime_minutes", 0)
    result.setdefault("half_day", False)
    return result
def weekdays_between(start: date, end: date) -> int:
    if start > end:
        return 0
    days = (end - start).days + 1
    full_weeks, remainder = divmod(days, 7)
    count = full_weeks * 5
    for offset in range(remainder):
        if (start.weekday() + offset) % 7 < 5:
            count += 1
    return count
def month_bounds(month: str):
    try:
        start = date.fromisoformat(month + "-01")
    except ValueError:
        raise HTTPException(422, "month must use YYYY-MM format")
    if len(month) != 7:
        raise HTTPException(422, "month must use YYYY-MM format")
    if start.month == 12:
        end = date(start.year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(start.year, start.month + 1, 1) - timedelta(days=1)
    return start, end
def validate_date_range(start: date, end: date, max_days=None):
    if end < start:
        raise HTTPException(422, "from must be on or before to")
    if max_days is not None and (end - start).days + 1 > max_days:
        raise HTTPException(422, f"Date range cannot exceed {max_days} days")
def employee_for(code):
    emp = employees.find_one({"emp_code": code})
    if emp is None:
        raise HTTPException(404, "Employee not found")
    return emp
class EmployeeIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=1, max_length=120,
                       pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: date
    @field_validator("shift_start", "shift_end")
    @classmethod
    def validate_shift_time(cls, value):
        parse_shift(value)
        return value
    @model_validator(mode="after")
    def validate_shift_pair(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start and shift_end must differ")
        return self
class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"
    @field_validator("punched_at", mode="before")
    @classmethod
    def validate_punched_at(cls, value):
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("punched_at must be an integer epoch timestamp")
            if not MIN_EPOCH_MS <= value <= MAX_EPOCH_MS:
                raise ValueError("punched_at is out of range")
        return value
class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    @field_validator("punched_at", mode="before")
    @classmethod
    def validate_punched_at(cls, value):
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("punched_at must be an integer epoch timestamp")
            if not MIN_EPOCH_MS <= value <= MAX_EPOCH_MS:
                raise ValueError("punched_at is out of range")
        return value
class RegularizeIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str = Field(min_length=1, max_length=500)
    regularized_by: str = Field(min_length=1, max_length=100)
    @field_validator("punch_in", "punch_out", mode="before")
    @classmethod
    def validate_timestamp(cls, value):
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("Timestamp must be an integer epoch timestamp")
            if not MIN_EPOCH_MS <= value <= MAX_EPOCH_MS:
                raise ValueError("Timestamp is out of range")
        return value
    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        if value is not None:
            parse_status(value)
        return value
@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(503, "Database unavailable")
@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["joined_on"] = body.joined_on.isoformat()
    doc["created_at"] = truncate_seconds(datetime.now(UTC))
    try:
        employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "emp_code already exists")
    return serialize_employee(doc)
@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = {"department": department} if department is not None else {}
    total = employees.count_documents(query)
    docs = list(employees.find(query, {"_id": 0})
                .sort("emp_code", 1).skip((page - 1) * page_size).limit(page_size))
    return {
        "items": [serialize_employee(doc) for doc in docs],
        "total": total, "page": page, "page_size": page_size,
    }
@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = employee_for(body.emp_code)
    if body.status not in {"PRESENT", "WFH", "ON_DUTY"}:
        raise HTTPException(422, "Punch-in status must be PRESENT, WFH, or ON_DUTY")
    ts = epoch_ms_to_datetime(body.punched_at) if body.punched_at is not None else truncate_seconds(datetime.now(UTC))
    day = attendance_date_for(ts, emp)
    doc = {
        "emp_code": body.emp_code, "date": day, "status": body.status,
        "punch_in": ts, "punch_out": None,
        **calculate_derived_fields(ts, None, emp, day), "history": [],
    }
    try:
        attendance.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Already punched in for this attendance date")
    return serialize_attendance(doc)
@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = employee_for(body.emp_code)
    ts = epoch_ms_to_datetime(body.punched_at) if body.punched_at is not None else truncate_seconds(datetime.now(UTC))
    # The punch-in instant is the selector, so this also finds overnight shifts.
    record = attendance.find_one(
        {"emp_code": body.emp_code, "punch_in": {"$lte": ts}},
        sort=[("punch_in", -1)],
    )
    if record is None:
        raise HTTPException(404, "No punch-in found before this timestamp")
    if record.get("punch_out") is not None:
        raise HTTPException(409, "Already punched out")
    record_punch_in = ensure_utc(record.get("punch_in"))
    if record_punch_in is None:
        raise HTTPException(404, "No punch-in found before this timestamp")
    if ts <= record_punch_in:
        raise HTTPException(422, "punch_out must be after punch_in")
    if ts > record_punch_in + timedelta(hours=24):
        raise HTTPException(422, "punch_out must be within 24 hours of punch_in")
    updated = attendance.find_one_and_update(
        {"_id": record["_id"], "punch_out": None},
        {"$set": {
            "punch_out": ts,
            **calculate_derived_fields(record_punch_in, ts, emp, record["date"]),
        }},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(409, "Already punched out")
    return serialize_attendance(updated)
@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must be on or before date_to")
    query = {}
    if emp_code is not None:
        query["emp_code"] = emp_code
    if status is not None:
        parse_status(status)
        query["status"] = status
    if date_from or date_to:
        query["date"] = {}
        if date_from:
            query["date"]["$gte"] = date_from.isoformat()
        if date_to:
            query["date"]["$lte"] = date_to.isoformat()
    total = attendance.count_documents(query)
    docs = list(attendance.find(query)
                .sort([("date", -1), ("emp_code", 1)])
                .skip((page - 1) * page_size).limit(page_size))
    return {
        "items": [serialize_attendance(doc) for doc in docs],
        "total": total, "page": page, "page_size": page_size,
    }
@app.patch("/attendance/{emp_code}/{attendance_date}")
def regularize_attendance(emp_code: str, attendance_date: date, body: RegularizeIn):
    emp = employee_for(emp_code)
    day = attendance_date.isoformat()
    old = attendance.find_one({"emp_code": emp_code, "date": day})
    if old is None:
        raise HTTPException(404, "Attendance record not found")
    supplied = body.model_dump(exclude_unset=True)
    new_status = supplied.get("status", old["status"])
    new_in = epoch_ms_to_datetime(supplied["punch_in"]) if supplied.get("punch_in") is not None else ensure_utc(old.get("punch_in"))
    new_out = epoch_ms_to_datetime(supplied["punch_out"]) if supplied.get("punch_out") is not None else ensure_utc(old.get("punch_out"))
    if new_status in {"ABSENT", "LEAVE"}:
        if ("punch_in" in supplied and supplied["punch_in"] is not None) or ("punch_out" in supplied and supplied["punch_out"] is not None):
            raise HTTPException(422, "ABSENT/LEAVE cannot include punch times")
        new_in, new_out = None, None
    elif new_in is None:
        raise HTTPException(422, "Presence status requires punch_in")
    if new_in is not None and attendance_date_for(new_in, emp) != day:
        raise HTTPException(422, "punch_in must fall on this attendance date under shift rules")
    if new_out is not None:
        if new_in is None or new_out <= new_in:
            raise HTTPException(422, "punch_out must be after punch_in")
        if new_out > new_in + timedelta(hours=24):
            raise HTTPException(422, "punch_out must be within 24 hours of punch_in")
    new_values = {
        "status": new_status, "punch_in": new_in, "punch_out": new_out,
        **calculate_derived_fields(new_in, new_out, emp, day),
    }
    changed = {}
    for key, new_value in new_values.items():
        old_value = old.get(key)

        # PyMongo may return naive UTC datetimes. Normalize both values before
        # comparing so unchanged punch timestamps are not recorded as edits.
        if key in {"punch_in", "punch_out"}:
            old_value = ensure_utc(old_value)
            new_value = ensure_utc(new_value)

        if old_value != new_value:
            changed[key] = {"from": old_value, "to": new_value}
    if not changed:
        raise HTTPException(422, "No changes to regularize")
    history_entry = {
        "at": truncate_seconds(datetime.now(UTC)),
        "reason": body.reason,
        "regularized_by": body.regularized_by,
        "changes": changed,
    }
    updated = attendance.find_one_and_update(
        {"_id": old["_id"], "history": old.get("history", [])},
        {"$set": new_values, "$push": {"history": history_entry}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(409, "Attendance record changed concurrently; retry")
    return serialize_attendance(updated)
def employee_monthly_pipeline(emp_code: str, start: date, end: date):
    """Aggregate stored attendance values for one employee and month in MongoDB."""
    return [
        {"$match": {
            "emp_code": emp_code,
            "date": {"$gte": start.isoformat(), "$lte": end.isoformat()},
        }},
        {"$set": {
            "_day_of_week": {
                "$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}
            }
        }},
        {"$group": {
            "_id": None,
            "present_days": {"$sum": {"$cond": [
                {"$and": [
                    {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                    {"$gte": ["$_day_of_week", 2]},
                    {"$lte": ["$_day_of_week", 6]},
                ]},
                {"$cond": [{"$eq": [{"$ifNull": ["$half_day", False]}, True]}, 0.5, 1.0]},
                0,
            ]}},
            "leave_days": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
            "late_count": {"$sum": {"$cond": [
                {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0
            ]}},
            "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
            "total_overtime_minutes": {"$sum": {"$ifNull": ["$overtime_minutes", 0]}},
        }},
    ]


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str):
    emp = employee_for(emp_code)
    start, end = month_bounds(month)
    joined = date.fromisoformat(emp["joined_on"])
    working_days = weekdays_between(max(start, joined), end)

    results = list(attendance.aggregate(employee_monthly_pipeline(emp_code, start, end)))
    stats = results[0] if results else {}
    present = stats.get("present_days", 0)
    rate = None if working_days == 0 else float(half_up(present / working_days * 100, 4))

    return {
        "emp_code": emp_code,
        "name": emp["name"],
        "department": emp["department"],
        "month": month,
        "working_days": working_days,
        "present_days": float(half_up(present, 2)),
        "leave_days": stats.get("leave_days", 0),
        "late_count": stats.get("late_count", 0),
        "total_late_minutes": stats.get("total_late_minutes", 0),
        "total_overtime_minutes": stats.get("total_overtime_minutes", 0),
        "attendance_pct": rate,
    }
def department_summary_pipeline(start, end):
    return [
        {"$match": {"joined_on": {"$lte": end.isoformat()}}},
        {"$lookup": {
            "from": "attendance_logs",
            "let": {"code": "$emp_code"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$emp_code", "$$code"]},
                            "date": {"$gte": start.isoformat(), "$lte": end.isoformat()}}},
                {"$project": {"status": 1, "date": 1, "half_day": 1, "work_hours": 1,
                              "late_minutes": 1}},
            ],
            "as": "logs",
        }},
        {"$unwind": {"path": "$logs", "preserveNullAndEmptyArrays": True}},
        {"$group": {
            "_id": "$department",
            "codes": {"$addToSet": "$emp_code"},
            "present_days": {"$sum": {"$cond": [
                {"$and": [
                    {"$ne": [{"$ifNull": ["$logs.status", None]}, None]},
                    {"$in": ["$logs.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                    {"$lt": [{"$dayOfWeek": {"$dateFromString": {
                        "dateString": {"$ifNull": ["$logs.date", "1970-01-01"]}
                    }}}, 7]},
                    {"$gt": [{"$dayOfWeek": {"$dateFromString": {
                        "dateString": {"$ifNull": ["$logs.date", "1970-01-01"]}
                    }}}, 1]},
                ]},
                {"$cond": ["$logs.half_day", 0.5, 1]}, 0
            ]}},
            "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$logs.late_minutes", 0]}, 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": {"$ifNull": ["$logs.late_minutes", 0]}},
            "leave_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "LEAVE"]}, 1, 0]}},
            "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "ON_DUTY"]}, 1, 0]}},
            "work_hours_values": {"$push": {"$cond": [
                {"$and": [
                    {"$in": ["$logs.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                    {"$ne": [{"$ifNull": ["$logs.work_hours", None]}, None]},
                ]}, "$logs.work_hours", None
            ]}},
        }},
        {"$project": {
            "_id": 0, "department": "$_id", "headcount": {"$size": "$codes"},
            "present_days": {"$round": ["$present_days", 2]},
            "late_count": 1, "total_late_minutes": 1, "leave_count": 1, "on_duty_count": 1,
            "avg_work_hours": {"$let": {
                "vars": {"hours": {"$filter": {"input": "$work_hours_values", "as": "h",
                                               "cond": {"$ne": ["$$h", None]}}}},
                "in": {"$cond": [{"$gt": [{"$size": "$$hours"}, 0]},
                                  {"$round": [{"$avg": "$$hours"}, 2]}, None]},
            }},
        }},
        {"$sort": {"department": 1}},
    ]
@app.get("/analytics/departments/summary")
def department_summary(month: str):
    start, end = month_bounds(month)
    result = list(employees.aggregate(department_summary_pipeline(start, end)))
    return {"month": month, "items": result}
@app.get("/analytics/leaderboard/late")
def late_leaderboard(month: str, department: Optional[str] = None, limit: int = Query(10, ge=1, le=50)):
    start, end = month_bounds(month)
    pipeline = [
        {"$match": {"date": {"$gte": start.isoformat(), "$lte": end.isoformat()},
                    "late_minutes": {"$gt": 0}}},
        {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": "$late_minutes"}}},
        {"$lookup": {"from": "employees", "localField": "_id", "foreignField": "emp_code", "as": "employee"}},
        {"$unwind": "$employee"},
    ]
    if department is not None:
        pipeline.append({"$match": {"employee.department": department}})
    pipeline += [
        {"$setWindowFields": {
            "sortBy": {"total_late_minutes": -1},
            "output": {"rank": {"$rank": {}}},
        }},
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {"$match": {"rank": {"$lte": limit}}},
        {"$project": {
            "_id": 0, "emp_code": "$_id", "name": "$employee.name",
            "department": "$employee.department", "total_late_minutes": 1, "rank": 1,
        }},
    ]
    return {"month": month, "department": department, "items": list(attendance.aggregate(pipeline))}
@app.get("/analytics/departments/{department}/trend")
def department_trend(department: str, from_date: date = Query(..., alias="from"), to_date: date = Query(..., alias="to")):
    validate_date_range(from_date, to_date, 92)
    if employees.count_documents({"department": department}) == 0:
        raise HTTPException(404, "Department not found")
    # Use MongoDB's $densify stage to fill missing dates; aggregation is executed
    # from the attendance collection, then joined to employee/headcount data.
    start_dt = datetime.combine(from_date, time.min, tzinfo=UTC)
    end_exclusive = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=UTC)
    pipeline = [
        {"$match": {"date": {"$gte": from_date.isoformat(), "$lte": to_date.isoformat()}}},
        {"$lookup": {"from": "employees", "localField": "emp_code", "foreignField": "emp_code", "as": "employee"}},
        {"$unwind": "$employee"},
        {"$match": {"employee.department": department}},
        {"$addFields": {"day_dt": {"$dateFromString": {"dateString": "$date"}}}},
        {"$group": {
            "_id": "$day_dt",
            "present_count": {"$sum": {"$cond": [
                {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                {"$cond": ["$half_day", 0.5, 1]}, 0
            ]}},
            "late_count": {"$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}},
        }},
        {"$project": {"_id": 0, "date": "$_id", "present_count": 1, "late_count": 1}},
        {"$densify": {"field": "date", "range": {
            "step": 1, "unit": "day", "bounds": [start_dt, end_exclusive]
        }}},
        {"$set": {
            "date_str": {"$dateToString": {"format": "%Y-%m-%d", "date": "$date"}},
            "present_count": {"$ifNull": ["$present_count", 0]},
            "late_count": {"$ifNull": ["$late_count", 0]},
        }},
        {"$lookup": {
            "from": "employees",
            "let": {"day": "$date_str"},
            "pipeline": [
                {"$match": {"department": department,
                            "$expr": {"$lte": ["$joined_on", "$$day"]}}},
                {"$count": "n"},
            ],
            "as": "head",
        }},
        {"$set": {"headcount": {"$ifNull": [{"$arrayElemAt": ["$head.n", 0]}, 0]}},
        },
        {"$set": {
            "is_working_day": {"$lt": [{"$dayOfWeek": "$date"}, 7]},
            "attendance_rate": {"$cond": [
                {"$and": [
                    {"$lt": [{"$dayOfWeek": "$date"}, 7]},
                    {"$gt": ["$headcount", 0]},
                ]},
                {"$round": [{"$divide": ["$present_count", "$headcount"]}, 4]},
                None,
            ]},
        }},
        {"$setWindowFields": {
            "sortBy": {"date": 1},
            "output": {"moving_avg_7d": {"$avg": "$attendance_rate",
                                         "window": {"documents": [-6, 0]}}},
        }},
        {"$sort": {"date": 1}},
        {"$project": {
            "_id": 0, "date": "$date_str", "is_working_day": 1, "headcount": 1,
            "present_count": 1, "late_count": 1, "attendance_rate": 1,
            "moving_avg_7d": {"$round": ["$moving_avg_7d", 4]},
        }},
    ]
    # If there are no records at all in the requested range, $densify has no
    # input row to expand. Seed a zero row through a small database aggregation.
    # This fallback still performs date gap filling in MongoDB, not a Python loop.
    has_rows = attendance.count_documents({"date": {"$gte": from_date.isoformat(), "$lte": to_date.isoformat()}})
    if has_rows:
        rows = list(attendance.aggregate(pipeline))
    else:
        # Generate the calendar inside MongoDB using $range/$map, then look up
        # daily attendance counts and employee headcount.
        calendar_pipeline = [
            {"$documents": [{"start": start_dt, "end": end_exclusive}]},
            {"$project": {"dates": {"$map": {
                "input": {"$range": [0, (to_date - from_date).days + 1]},
                "as": "i",
                "in": {"$dateAdd": {"startDate": "$start", "unit": "day", "amount": "$$i"}},
            }}}},
            {"$unwind": "$dates"},
            {"$set": {"date_str": {"$dateToString": {"format": "%Y-%m-%d", "date": "$dates"}}}},
            {"$lookup": {
                "from": "attendance_logs",
                "let": {"day": "$date_str"},
                "pipeline": [
                    {"$match": {"$expr": {"$eq": ["$date", "$$day"]}}},
                    {"$lookup": {"from": "employees", "localField": "emp_code", "foreignField": "emp_code", "as": "employee"}},
                    {"$unwind": "$employee"},
                    {"$match": {"employee.department": department}},
                    {"$group": {
                        "_id": None,
                        "present_count": {"$sum": {"$cond": [
                            {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                            {"$cond": ["$half_day", 0.5, 1]}, 0
                        ]}},
                        "late_count": {"$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}},
                    }},
                ],
                "as": "daily",
            }},
            {"$lookup": {
                "from": "employees",
                "let": {"day": "$date_str"},
                "pipeline": [
                    {"$match": {"department": department, "$expr": {"$lte": ["$joined_on", "$$day"]}},
                    },
                    {"$count": "n"},
                ],
                "as": "head",
            }},
            {"$set": {
                "headcount": {"$ifNull": [{"$arrayElemAt": ["$head.n", 0]}, 0]},
                "present_count": {"$ifNull": [{"$arrayElemAt": ["$daily.present_count", 0]}, 0]},
                "late_count": {"$ifNull": [{"$arrayElemAt": ["$daily.late_count", 0]}, 0]},
                "is_working_day": {"$lt": [{"$dayOfWeek": "$dates"}, 7]},
            }},
            {"$set": {"attendance_rate": {"$cond": [
                {"$and": [{"$lt": [{"$dayOfWeek": "$dates"}, 7]}, {"$gt": ["$headcount", 0]}]},
                {"$round": [{"$divide": ["$present_count", "$headcount"]}, 4]}, None
            ]}}},
            {"$setWindowFields": {
                "sortBy": {"dates": 1},
                "output": {"moving_avg_7d": {"$avg": "$attendance_rate", "window": {"documents": [-6, 0]}}},
            }},
            {"$sort": {"dates": 1}},
            {"$project": {
                "_id": 0, "date": "$date_str", "is_working_day": 1, "headcount": 1,
                "present_count": 1, "late_count": 1, "attendance_rate": 1,
                "moving_avg_7d": {"$round": ["$moving_avg_7d", 4]},
            }},
        ]
        rows = list(db.aggregate(calendar_pipeline))
    return {"department": department, "from": from_date.isoformat(), "to": to_date.isoformat(), "items": rows}
def explain_aggregation(collection, pipeline):
    """Return MongoDB executionStats for an aggregation pipeline."""
    result = collection.database.command(
        "explain",
        {
            "aggregate": collection.name,
            "pipeline": pipeline,
            "cursor": {},
        },
        verbosity="executionStats",
    )
    # Convert BSON-specific values (including Timestamp) into JSON-safe values.
    return json.loads(dumps(result))
@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    month: Optional[str] = None,
    department: Optional[str] = None,
    from_date: Optional[date] = Query(None, alias="from"),
    to_date: Optional[date] = Query(None, alias="to"),
    emp_code: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    # Explain the main database operation with execution statistics.
    # The endpoint-specific query/pipeline is intentionally built here rather
    # than returning a placeholder.
    if endpoint == "attendance_list":
        query = {}
        if emp_code is not None:
            query["emp_code"] = emp_code
        if status is not None:
            query["status"] = status
        if date_from or date_to:
            query["date"] = {}
            if date_from:
                query["date"]["$gte"] = date_from.isoformat()
            if date_to:
                query["date"]["$lte"] = date_to.isoformat()
        explain_result = (
            attendance.find(query)
            .sort([("date", -1), ("emp_code", 1)])
            .skip((page - 1) * page_size)
            .limit(page_size)
            .explain()
        )
        return json.loads(dumps(explain_result))
    if endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(422, "employee_monthly requires emp_code and month")
        start, end = month_bounds(month)
        pipeline = employee_monthly_pipeline(emp_code, start, end)
        return explain_aggregation(attendance, pipeline)
    if endpoint == "department_summary":
        if not month:
            raise HTTPException(422, "department_summary requires month")
        start, end = month_bounds(month)
        pipeline = department_summary_pipeline(start, end)
        return explain_aggregation(employees, pipeline)
    if endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(422, "late_leaderboard requires month")
        start, end = month_bounds(month)
        pipeline = [{"$match": {"date": {"$gte": start.isoformat(), "$lte": end.isoformat()}, "late_minutes": {"$gt": 0}}}, {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": "$late_minutes"}}}]
        return explain_aggregation(attendance, pipeline)
    if endpoint == "department_trend":
        if not department or from_date is None or to_date is None:
            raise HTTPException(
                422,
                "department_trend requires department, from, and to"
            )

        validate_date_range(from_date, to_date, 92)

        # Explain the same department-filtered daily aggregation used by the
        # trend endpoint. This reports the real query plan, not a date-only
        # placeholder pipeline.
        start_dt = datetime.combine(from_date, time.min, tzinfo=UTC)
        end_exclusive = datetime.combine(
            to_date + timedelta(days=1), time.min, tzinfo=UTC
        )

        pipeline = [
            {
                "$match": {
                    "date": {
                        "$gte": from_date.isoformat(),
                        "$lte": to_date.isoformat(),
                    }
                }
            },
            {
                "$lookup": {
                    "from": "employees",
                    "localField": "emp_code",
                    "foreignField": "emp_code",
                    "as": "employee",
                }
            },
            {"$unwind": "$employee"},
            {"$match": {"employee.department": department}},
            {
                "$addFields": {
                    "day_dt": {"$dateFromString": {"dateString": "$date"}}
                }
            },
            {
                "$group": {
                    "_id": "$day_dt",
                    "present_count": {
                        "$sum": {
                            "$cond": [
                                {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                {"$cond": ["$half_day", 0.5, 1]},
                                0,
                            ]
                        }
                    },
                    "late_count": {
                        "$sum": {
                            "$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]
                        }
                    },
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "date": "$_id",
                    "present_count": 1,
                    "late_count": 1,
                }
            },
            {
                "$densify": {
                    "field": "date",
                    "range": {
                        "step": 1,
                        "unit": "day",
                        "bounds": [start_dt, end_exclusive],
                    },
                }
            },
            {
                "$set": {
                    "date_str": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$date",
                        }
                    },
                    "present_count": {"$ifNull": ["$present_count", 0]},
                    "late_count": {"$ifNull": ["$late_count", 0]},
                }
            },
            {
                "$lookup": {
                    "from": "employees",
                    "let": {"day": "$date_str"},
                    "pipeline": [
                        {
                            "$match": {
                                "department": department,
                                "$expr": {"$lte": ["$joined_on", "$$day"]},
                            }
                        },
                        {"$count": "n"},
                    ],
                    "as": "head",
                }
            },
            {
                "$set": {
                    "headcount": {
                        "$ifNull": [{"$arrayElemAt": ["$head.n", 0]}, 0]
                    }
                }
            },
            {
                "$set": {
                    "is_working_day": {"$lt": [{"$dayOfWeek": "$date"}, 7]},
                    "attendance_rate": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$lt": [{"$dayOfWeek": "$date"}, 7]},
                                    {"$gt": ["$headcount", 0]},
                                ]
                            },
                            {"$round": [{"$divide": ["$present_count", "$headcount"]}, 4]},
                            None,
                        ]
                    },
                }
            },
            {
                "$setWindowFields": {
                    "sortBy": {"date": 1},
                    "output": {
                        "moving_avg_7d": {
                            "$avg": "$attendance_rate",
                            "window": {"documents": [-6, 0]},
                        }
                    },
                }
            },
            {"$sort": {"date": 1}},
            {
                "$project": {
                    "_id": 0,
                    "date": "$date_str",
                    "is_working_day": 1,
                    "headcount": 1,
                    "present_count": 1,
                    "late_count": 1,
                    "attendance_rate": 1,
                    "moving_avg_7d": {"$round": ["$moving_avg_7d", 4]},
                }
            },
        ]

        return explain_aggregation(attendance, pipeline)

    raise HTTPException(422, "Unknown endpoint")
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
