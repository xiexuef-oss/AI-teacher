"""Prevent storage of authenticated draft responses, including errors and replays."""

from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from tutor_api.errors import ApiError


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private(request):
            headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
            try:
                response = await handler(request)
            except ApiError as error:
                error.headers.update(headers)
                raise
            except RequestValidationError as error:
                response = await request.app.exception_handlers[RequestValidationError](
                    request, error
                )
            response.headers.update(headers)
            return response

        return private
