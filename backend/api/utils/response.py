from rest_framework.response import Response

def pydantic_response(model_instance, status=200, **kwargs) -> Response:
    """Return a DRF Response from any Pydantic model."""
    return Response(model_instance.model_dump(mode="json"), status=status, **kwargs)