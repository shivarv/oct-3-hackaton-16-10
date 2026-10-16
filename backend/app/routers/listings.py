from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.db import DbSession
from app.models import Listing
from app.schemas import ListingCreate, ListingRead

router = APIRouter(prefix="/api/listings", tags=["listings"])


@router.get("", response_model=list[ListingRead])
def list_listings(db: DbSession, city: str | None = None):
    stmt = select(Listing).order_by(Listing.created_at.desc())
    if city:
        stmt = stmt.where(Listing.city.ilike(city))
    return db.scalars(stmt).all()


@router.get("/{listing_id}", response_model=ListingRead)
def get_listing(listing_id: int, db: DbSession):
    listing = db.get(Listing, listing_id)
    if listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    return listing


@router.post("", response_model=ListingRead, status_code=status.HTTP_201_CREATED)
def create_listing(payload: ListingCreate, db: DbSession):
    listing = Listing(**payload.model_dump())
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


@router.delete("/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_listing(listing_id: int, db: DbSession):
    listing = db.get(Listing, listing_id)
    if listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    db.delete(listing)
    db.commit()
