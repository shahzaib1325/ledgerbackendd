# Module 07 — Staff & Payroll

## 1. Module Overview

| Attribute | Value |
|-----------|-------|
| Module Name | Staff & Payroll |
| Prefix | `/api/v1/staff` |
| Files | `models/staff.py`, `schemas/staff.py`, `api/v1/endpoints/staff.py`, `services/staff_service.py`, `repositories/staff_repo.py` |
| Dependencies | Transactions module (salary payment in account ledger), Production module (labor tracking) |

The Staff module manages all employees — both permanent (monthly salary) and temporary (daily rate). It tracks salary structures with allowances and deductions, records daily attendance, processes monthly payroll, and handles salary advances.

---

## 2. Functional Requirements

- **FR-STF-01**: Add permanent and temporary staff with contact info and designation.
- **FR-STF-02**: Maintain versioned salary structures with allowances and deductions as key-value pairs.
- **FR-STF-03**: Record daily attendance per staff member.
- **FR-STF-04**: Process monthly salary payments, auto-calculating gross, deductions, and net salary.
- **FR-STF-05**: Record salary advances and auto-deduct from the specified month's payroll.
- **FR-STF-06**: For temporary staff, compute daily rate from basic salary and actual days attended.
- **FR-STF-07**: Prevent duplicate salary processing for the same month.

---

## 3. Data Models

### `Staff`
```python
class Staff(Base, TimestampMixin):
    __tablename__ = "staff"

    id: int
    name: str (max 200)
    phone: str | None
    cnic: str | None (unique, max 20)       # National ID
    address: str | None
    join_date: date
    staff_type: StaffType                   # permanent | temporary
    designation: str | None
    department: str | None
    is_active: bool (default True)
    created_by: int (FK → users)
```

### `SalaryStructure`
```python
class SalaryStructure(Base):
    __tablename__ = "salary_structures"

    id: int
    staff_id: int (FK → staff)
    basic_salary: Decimal (> 0)
    allowances: dict  # JSONB: {"transport": 2000, "meal": 1500, "housing": 5000}
    deductions: dict  # JSONB: {"tax": 500, "insurance": 200, "pf": 1000}
    effective_from: date
    effective_to: date | None       # NULL = currently active structure
    created_by: int (FK → users)
    created_at: datetime
```

### `Attendance`
```python
class Attendance(Base):
    __tablename__ = "attendance"

    id: int
    staff_id: int (FK → staff)
    date: date
    status: AttendanceStatus        # present | absent | half_day | leave
    notes: str | None
    created_by: int (FK → users)
    # Unique: (staff_id, date)
```

### `StaffPayment`
```python
class StaffPayment(Base):
    __tablename__ = "staff_payments"

    id: int
    staff_id: int (FK → staff)
    payment_month: int (1-12)
    payment_year: int
    gross_salary: Decimal
    total_allowances: Decimal
    total_deductions: Decimal
    advance_deduction: Decimal
    net_salary: Decimal
    payment_mode: PaymentMode
    account_id: int | None (FK → accounts)
    paid_at: datetime
    notes: str | None
    created_by: int (FK → users)
    # Unique: (staff_id, payment_month, payment_year)
```

### `Advance`
```python
class Advance(Base):
    __tablename__ = "advances"

    id: int
    staff_id: int (FK → staff)
    amount: Decimal (> 0)
    deduct_from_month: int (1-12)
    deduct_from_year: int
    reason: str | None
    is_deducted: bool (default False)   # set to True when payroll is processed
    paid_at: datetime
    created_by: int (FK → users)
```

---

## 4. Pydantic Schemas

```python
class StaffCreate(BaseModel):
    name: str
    phone: str | None
    cnic: str | None
    address: str | None
    join_date: date
    staff_type: StaffType
    designation: str | None
    department: str | None

class StaffUpdate(BaseModel):
    name: str | None
    phone: str | None
    address: str | None
    designation: str | None
    department: str | None

class SalaryStructureCreate(BaseModel):
    basic_salary: Decimal (> 0)
    allowances: dict[str, Decimal] (default {})
    deductions: dict[str, Decimal] (default {})
    effective_from: date

class AttendanceCreate(BaseModel):
    date: date
    status: AttendanceStatus
    notes: str | None

class AttendanceBulkCreate(BaseModel):
    records: list[AttendanceCreate] (min 1, max 31)

class SalaryPaymentProcess(BaseModel):
    payment_month: int (1-12)
    payment_year: int
    payment_mode: PaymentMode
    account_id: int | None
    notes: str | None
    # All other fields auto-calculated

class AdvanceCreate(BaseModel):
    amount: Decimal (> 0)
    deduct_from_month: int (1-12)
    deduct_from_year: int
    reason: str | None

class SalaryCalculationOut(BaseModel):
    staff_id: int
    staff_name: str
    payment_month: int
    payment_year: int
    basic_salary: Decimal
    allowances_breakdown: dict[str, Decimal]
    total_allowances: Decimal
    deductions_breakdown: dict[str, Decimal]
    total_deductions: Decimal
    advance_deduction: Decimal
    gross_salary: Decimal
    net_salary: Decimal
    working_days: int             # for temporary staff
    days_present: int             # from attendance
    is_already_paid: bool

class StaffPaymentOut(BaseModel):
    id: int
    staff: StaffListOut
    payment_month: int
    payment_year: int
    gross_salary: Decimal
    total_allowances: Decimal
    total_deductions: Decimal
    advance_deduction: Decimal
    net_salary: Decimal
    payment_mode: PaymentMode
    paid_at: datetime
```

---

## 5. API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/staff` | read | List staff (paginated + filters) |
| POST | `/staff` | write | Add staff member |
| GET | `/staff/{id}` | read | Staff detail |
| PUT | `/staff/{id}` | write | Update |
| DELETE | `/staff/{id}` | delete | Deactivate |
| GET | `/staff/{id}/salary-structure` | read | Active salary structure |
| POST | `/staff/{id}/salary-structure` | write | Set new salary structure |
| GET | `/staff/{id}/salary-history` | read | All salary structure history |
| GET | `/staff/{id}/attendance` | read | Monthly attendance |
| POST | `/staff/{id}/attendance` | write | Record single day attendance |
| POST | `/staff/{id}/attendance/bulk` | write | Record multiple days at once |
| GET | `/staff/{id}/payments` | read | Salary payment history |
| GET | `/staff/{id}/salary-preview` | read | Preview salary before processing |
| POST | `/staff/{id}/payments/process` | write | Process salary payment |
| GET | `/staff/{id}/advances` | read | Advance history |
| POST | `/staff/{id}/advances` | write | Record advance |
| GET | `/staff/payments/summary` | read | All payments summary (Staff Payments Report) |

### Query Parameters (GET /staff)
| Param | Type | Description |
|-------|------|-------------|
| `search` | string | Name search |
| `staff_type` | permanent\|temporary | |
| `department` | string | Filter by department |
| `is_active` | bool | Default true |
| `page`, `limit` | int | |

### Query Parameters (GET /staff/{id}/attendance)
| Param | Type | Description |
|-------|------|-------------|
| `month` | int (1-12) | Required |
| `year` | int | Required |

---

## 6. Service Layer — `StaffService`

```python
class StaffService:

    async def set_salary_structure(db, staff_id, structure_in, actor_id) -> SalaryStructure:
        """
        1. Fetch currently active structure (effective_to IS NULL)
        2. Set effective_to = structure_in.effective_from - 1 day (close previous)
        3. Create new structure with effective_to = NULL
        4. Audit log
        """

    async def calculate_salary(db, staff_id, month, year) -> SalaryCalculationOut:
        """
        Called by preview and process endpoints.

        For PERMANENT staff:
          gross_salary = basic_salary
          total_allowances = sum(allowances.values())
          total_deductions = sum(deductions.values())
          advance = sum of advances for this month/year (is_deducted=False)
          net_salary = gross_salary + total_allowances - total_deductions - advance

        For TEMPORARY staff:
          working_days = number of workdays in month (Mon-Sat or configured)
          days_present = count(attendance where status IN (present, half_day))
            (half_day counts as 0.5)
          daily_rate = basic_salary / working_days
          gross_salary = daily_rate × days_present
          net_salary = gross_salary - deductions - advance
        """

    async def process_payment(db, staff_id, payment_in, actor_id) -> StaffPayment:
        """
        1. Call calculate_salary() to get breakdown
        2. Check not already paid for this month/year (unique constraint)
        3. Create StaffPayment record
        4. Mark all advances for this month as is_deducted = True
        5. Call TransactionService.record() to debit the account
        6. Audit log
        All in one DB transaction
        """

    async def record_attendance(db, staff_id, attendance_in, actor_id) -> Attendance:
        """
        Upsert attendance: if record exists for (staff_id, date), update it.
        """
```

---

## 7. Salary Calculation Detail

### Permanent Staff
```
Gross Salary = Basic Salary
Total Allowances = transport + meal + housing + other allowances
Total Deductions = tax + insurance + pf + other deductions
Advance Deduction = SUM of advances marked for this month (pending deduction)
Net Salary = Gross + Total Allowances - Total Deductions - Advance Deduction
```

### Temporary Staff
```
Standard Working Days = count of working days in the month
  (by default Mon-Sat = 26 days, configurable)

Days Present = COUNT WHERE attendance.status = 'present'
            + 0.5 × COUNT WHERE attendance.status = 'half_day'

Daily Rate = Basic Salary / Standard Working Days

Gross Salary = Daily Rate × Days Present
Net Salary = Gross Salary - Deductions - Advances
```

---

## 8. Salary Structure Versioning

The salary structure is versioned to maintain historical accuracy:

```
Staff A:
  Structure 1: effective_from=2025-01-01, effective_to=2025-12-31, basic=30000
  Structure 2: effective_from=2026-01-01, effective_to=NULL,       basic=35000

When calculating salary for month=1, year=2026:
  → Use Structure 2 (effective_to IS NULL and effective_from <= first day of month)
```

**Rule:** When setting a new structure, always close the previous one by setting `effective_to = new_structure.effective_from - 1 day`.

---

## 9. Business Rules

| Rule | Detail |
|------|--------|
| One payment per month | `UNIQUE (staff_id, payment_month, payment_year)` — prevents duplicate payroll |
| Advance deduction | Auto-included in salary calculation for the specified deduction month |
| Deactivation | Setting `is_active = False` keeps all history intact |
| CNIC uniqueness | If provided, must be globally unique across all staff |
| Attendance upsert | Re-recording attendance for same date replaces the previous record |
| Advance paid_at | Date the cash was handed to the employee (not the deduction month) |
| Temporary staff payment | If no attendance records exist, `days_present = 0` and salary = 0 |

---

## 10. Error Handling

| Scenario | Exception | HTTP Code |
|----------|-----------|-----------|
| Staff not found | `NotFoundException` | 404 |
| Duplicate salary for month | `DuplicateSalaryPaymentError` | 409 |
| No active salary structure | `ValidationException` | 422 |
| Advance > net salary | Warning (not error) — logged | 200 + warning |
| Duplicate attendance date | Upsert (no error) | 200 |
| CNIC already exists | `ConflictException` | 409 |

---

## 11. Inter-Module Interactions

| Interaction | Direction | Description |
|-------------|-----------|-------------|
| `StaffService.process_payment()` → `TransactionService.record()` | Outbound | Debit account with salary payout |
| `ProductionService` → `StaffRepository` | Inbound | Links staff to production labor records |
| `ReportService` → `StaffRepository` | Inbound | Staff payments report |
