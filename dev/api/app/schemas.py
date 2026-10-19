from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

ACCOUNT_ID = r"^ACC-[A-Z0-9-]{1,20}$"


class TransactionIn(BaseModel):
    from_account: str = Field(pattern=ACCOUNT_ID, examples=["ACC-ALICE"])
    to_account: str = Field(pattern=ACCOUNT_ID, examples=["ACC-MERCHANT"])
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2, examples=["12.50"])
    currency: str = Field("EUR", pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def different_accounts(self):
        if self.from_account == self.to_account:
            raise ValueError("from_account et to_account doivent differer")
        return self


class TransactionOut(BaseModel):
    id: UUID
    from_account: str
    to_account: str
    amount: Decimal
    currency: str
    status: str
    created_by: str
    created_at: datetime


class AccountOut(BaseModel):
    id: str
    owner: str
    balance: Decimal
    currency: str


class LedgerCheck(BaseModel):
    consistent: bool
    mismatches: list[str]
