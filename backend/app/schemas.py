from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ListingBase(BaseModel):
    title: str = Field(max_length=200)
    description: str | None = None
    address: str = Field(max_length=300)
    city: str = Field(max_length=100)
    price: Decimal = Field(ge=0)
    bedrooms: int = Field(default=1, ge=0)
    bathrooms: int = Field(default=1, ge=0)


class ListingCreate(ListingBase):
    pass


class ListingRead(ListingBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
