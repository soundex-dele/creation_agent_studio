"""
Custom exceptions for Agent Studio.
"""
from rest_framework.exceptions import APIException


class BaseServiceError(APIException):
    """Base exception for service-level errors."""
    status_code = 500
    default_detail = 'A server error occurred.'
    default_code = 'service_error'


class NotFoundException(APIException):
    """Exception raised when a resource is not found."""
    status_code = 404
    default_detail = 'Resource not found.'
    default_code = 'not_found'


class PermissionDeniedException(APIException):
    """Exception raised when user lacks permission."""
    status_code = 403
    default_detail = 'You do not have permission to perform this action.'
    default_code = 'permission_denied'


class BadRequestException(APIException):
    """Exception raised for bad requests."""
    status_code = 400
    default_detail = 'Bad request.'
    default_code = 'bad_request'


class ConflictException(APIException):
    """Exception raised for conflicts."""
    status_code = 409
    default_detail = 'Resource conflict.'
    default_code = 'conflict'
