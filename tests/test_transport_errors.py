import unittest

from tools.transport_errors import (
    extract_business_message,
    format_step_failure,
    is_retryable_tool_error,
)


class TransportErrorsTests(unittest.TestCase):
    def test_extract_business_message(self) -> None:
        err = (
            "HTTP error 403: Forbidden - {'error': {'code': "
            "'ParkingSpotMaxCountReached', 'message': '车位号最多只能保存5个！'}}"
        )
        self.assertEqual(extract_business_message(err), "车位号最多只能保存5个！")

    def test_non_retryable_403(self) -> None:
        err = "HTTP error 403: Forbidden - {'error': {'message': '车位号最多只能保存5个！'}}"
        self.assertFalse(is_retryable_tool_error(err))

    def test_retryable_503(self) -> None:
        self.assertTrue(is_retryable_tool_error("HTTP error 503: Service Unavailable"))

    def test_extract_validation_errors(self) -> None:
        err = (
            "HTTP error 400: Bad Request - {'error': {'message': 'Your request is not valid!', "
            "'details': 'The following errors were detected during validation.\\n "
            "- The ParkingSpot field is required.\\n', "
            "'validationErrors': [{'message': 'The ParkingSpot field is required.', "
            "'members': ['parkingSpot']}]}}"
        )
        self.assertEqual(
            extract_business_message(err),
            "The ParkingSpot field is required.",
        )
        err = "HTTP error 403: Forbidden - {'error': {'message': '车位号最多只能保存5个！'}}"
        text = format_step_failure(err, tool_name="Vehicle_AddSpotNumber")
        self.assertIn("车位号最多只能保存5个", text)
        self.assertIn("Vehicle_AddSpotNumber", text)


if __name__ == "__main__":
    unittest.main()
