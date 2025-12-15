"""
Announcement endpoints for the High School Management System API
"""

from datetime import date
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, validator
from pymongo import ReturnDocument

from ..database import announcements_collection, teachers_collection


router = APIRouter(prefix="/announcements", tags=["announcements"])


class AnnouncementPayload(BaseModel):
    """Payload model used for create and update operations."""

    title: str = Field(..., min_length=1, max_length=120)
    message: str = Field(..., min_length=1, max_length=800)
    start_date: Optional[date] = Field(None, description="Optional start date (YYYY-MM-DD)")
    end_date: date = Field(..., description="Required end/expiration date (YYYY-MM-DD)")

    @validator("end_date")
    def validate_end_date(cls, end: date, values: Dict[str, Any]) -> date:
        start = values.get("start_date")
        if start and end < start:
            raise ValueError("End date cannot be before start date")
        return end


class AnnouncementResponse(BaseModel):
    id: str
    title: str
    message: str
    start_date: Optional[date]
    end_date: date


# Helpers

def _require_teacher(username: Optional[str]):
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required for this action")

    teacher = teachers_collection.find_one({"_id": username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")
    return teacher


def _parse_optional_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _serialize_payload(payload: AnnouncementPayload) -> Dict[str, Any]:
    return {
        "title": payload.title.strip(),
        "message": payload.message.strip(),
        "start_date": payload.start_date.isoformat() if payload.start_date else None,
        "end_date": payload.end_date.isoformat(),
    }


def _doc_to_response(doc: Dict[str, Any]) -> AnnouncementResponse:
    return AnnouncementResponse(
        id=str(doc.get("_id")),
        title=doc.get("title", ""),
        message=doc.get("message", ""),
        start_date=_parse_optional_date(doc.get("start_date")),
        end_date=_parse_optional_date(doc.get("end_date")) or date.today(),
    )


# Routes


@router.get("", response_model=List[AnnouncementResponse])
@router.get("/", response_model=List[AnnouncementResponse])
def list_announcements(
    include_expired: bool = Query(False, description="Include announcements past their end date"),
    include_future: bool = Query(False, description="Include announcements that start in the future"),
) -> List[AnnouncementResponse]:
    today_iso = date.today().isoformat()

    query: Dict[str, Any] = {}
    if not include_expired:
        query["end_date"] = {"$gte": today_iso}
        if not include_future:
            query["$or"] = [
                {"start_date": {"$exists": False}},
                {"start_date": None},
                {"start_date": {"$lte": today_iso}},
            ]

    cursor = announcements_collection.find(query).sort("end_date", 1)
    return [_doc_to_response(doc) for doc in cursor]


@router.post("", response_model=AnnouncementResponse)
@router.post("/", response_model=AnnouncementResponse)
def create_announcement(payload: AnnouncementPayload, teacher_username: Optional[str] = Query(None)) -> AnnouncementResponse:
    _require_teacher(teacher_username)

    serialized = _serialize_payload(payload)
    result = announcements_collection.insert_one(serialized)
    created = announcements_collection.find_one({"_id": result.inserted_id})
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create announcement")
    return _doc_to_response(created)


@router.put("/{announcement_id}", response_model=AnnouncementResponse)
def update_announcement(
    announcement_id: str,
    payload: AnnouncementPayload,
    teacher_username: Optional[str] = Query(None),
) -> AnnouncementResponse:
    _require_teacher(teacher_username)

    try:
        object_id = ObjectId(announcement_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Announcement not found")

    serialized = _serialize_payload(payload)
    result = announcements_collection.find_one_and_update(
        {"_id": object_id}, {"$set": serialized}, return_document=ReturnDocument.AFTER
    )

    if not result:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return _doc_to_response(result)


@router.delete("/{announcement_id}")
def delete_announcement(announcement_id: str, teacher_username: Optional[str] = Query(None)) -> Dict[str, str]:
    _require_teacher(teacher_username)

    try:
        object_id = ObjectId(announcement_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Announcement not found")

    delete_result = announcements_collection.delete_one({"_id": object_id})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}