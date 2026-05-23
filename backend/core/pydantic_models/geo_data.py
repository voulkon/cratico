from typing import Any, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

Coord = Tuple[float, float]  # (lon, lat)


class BoundingBox(BaseModel):
    south: float
    north: float
    west: float
    east: float

    @model_validator(mode="before")
    @classmethod
    def from_list(cls, v):
        if isinstance(v, list) and len(v) == 4:
            south, north, west, east = map(float, v)
            return {"south": south, "north": north, "west": west, "east": east}
        return v


class GeoJSON(BaseModel):
    # Accept any geometry type
    type_: str = Field(alias="type")
    # Make coordinates flexible to handle different geometry types
    coordinates: Any

    model_config = ConfigDict(extra="allow")


class NominatimResult(BaseModel):
    place_id: int
    lat: float
    lon: float
    category: str
    type: str
    place_rank: int
    importance: float
    addresstype: str | None = None
    name: str | None = None
    display_name: str
    boundingbox: BoundingBox
    geojson: GeoJSON

    model_config = ConfigDict(extra="allow")
