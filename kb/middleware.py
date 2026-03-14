from loguru import logger
from django.http import HttpRequest, HttpResponse
from typing import Callable


class RequestLoggingMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Log the request before it gets processed
        logger.info(f"Received request: {request.method} {request.path}")

        response = self.get_response(request)

        return response
