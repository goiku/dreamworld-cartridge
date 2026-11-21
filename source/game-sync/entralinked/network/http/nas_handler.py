"""The Nintendo authentication server (nas.nintendowifi.net)."""
import logging
from dataclasses import dataclass, fields
from datetime import datetime
from enum import IntEnum
from http import HTTPStatus

from flask import Blueprint, Response, request
from flask.typing import ResponseReturnValue

from ...context import Context
from ...model.user.user_manager import is_valid_user_id
from ...utility.url_encoded_form import decode_form, encode_form

logger = logging.getLogger(__name__)

GAMESPY_SERVICE = "gamespy"
SERVICES = {
    "0000": ("external", "PGL"),
    "9000": ("dls1.nintendowifi.net", "DLS1"),
}


class NasReturnCode(IntEnum):
    """`returncd` values."""

    SUCCESS = 1
    REGISTRATION_SUCCESS = 2
    INTERNAL_SERVER_ERROR = 100
    BAD_REQUEST = 102
    USER_ALREADY_EXISTS = 104
    USER_EXPIRED = 108
    USER_NOT_FOUND = 204

    def __str__(self) -> str:
        """Return the code as three digits."""
        return f"{self.value:03d}"


@dataclass
class NasRequest:
    userid: str
    passwd: str
    action: str
    gsbrcd: str | None = None  # branch code: which GameSpy profile to log in to
    svc: str | None = None


def nas_response(returncd: NasReturnCode = NasReturnCode.SUCCESS, **fields: str) -> ResponseReturnValue:
    body = encode_form({"returncd": returncd, "datetime": datetime.now().strftime("%y%m%d%H%M%S"), **fields})
    return body, HTTPStatus.OK, {"Content-Type": "application/x-www-form-urlencoded"}


class NasHandler:
    """Handle Nintendo WFC authentication and the pre-deposit name check."""

    def __init__(self, context: Context) -> None:
        self.configuration = context.configuration
        self.user_manager = context.user_manager
        self._actions = {
            "login": self.handle_login,
            "acctcreate": self.handle_create_account,
            "SVCLOC": self.handle_retrieve_service_location,
        }

    def blueprint(self) -> Blueprint:
        blueprint = Blueprint("nas", __name__)
        blueprint.add_url_rule("/ac", view_func=self.handle_nas_request, methods=["POST"])
        blueprint.add_url_rule("/pr", view_func=self.check_names, methods=["POST"])
        return blueprint

    @staticmethod
    def check_names() -> ResponseReturnValue:
        """Check the tab-separated names sent between GTS validation and deposit."""
        from utils.badwords import contains_bad_word

        request.max_content_length = 65536
        try:
            encoded = decode_form(request.get_data(as_text=True))["words"].encode("latin-1")
            if encoded.startswith((b"\xff\xfe", b"\xfe\xff")):
                names = encoded.decode("utf-16")
            elif b"\t\0" in encoded or b"\0" in encoded[:-1]:
                names = encoded.decode("utf-16-le")
            else:
                try:
                    names = encoded.decode("utf-8")
                except UnicodeDecodeError:
                    # A single Japanese UTF-16LE name may contain no zero bytes.
                    names = encoded.decode("utf-16-le")
        except (KeyError, ValueError):
            return nas_response(NasReturnCode.BAD_REQUEST)
        flags = "".join("1" if contains_bad_word(name) else "0" for name in names.rstrip("\0").split("\t"))
        fields = {"returncd": "000", "datetime": datetime.now().strftime("%Y%m%d%H%M%S"), "prwords": flags}
        fields.update({"prwords" + region: flags for region in "ACEJKP"})
        return Response(encode_form(fields), mimetype="text/plain", headers={"NODE": "wifiappe1", "Cache-Control": "no-store"})

    def handle_nas_request(self) -> ResponseReturnValue:
        """Decode the form and hand it to the handler of its `action`."""
        known_fields = {f.name for f in fields(NasRequest)}

        try:
            form = decode_form(request.get_data(as_text=True))
            nas_request = NasRequest(**{key: value for key, value in form.items() if key in known_fields})
        except (ValueError, TypeError):  # bad base64, or a required field is missing
            logger.exception("Malformed NAS request")
            return nas_response(NasReturnCode.BAD_REQUEST)

        logger.debug("Received NAS %s request from user %s", nas_request.action, nas_request.userid)
        handler = self._actions.get(nas_request.action)

        if handler is None:
            logger.error("Invalid NAS request action: %s", nas_request.action)
            return nas_response(NasReturnCode.BAD_REQUEST)

        return handler(nas_request)

    def handle_login(self, req: NasRequest) -> ResponseReturnValue:
        """Log in and start a GameSpy session."""
        if req.gsbrcd is None:
            logger.debug("Rejecting NAS login request because no branch code is present")
            return nas_response(NasReturnCode.BAD_REQUEST)

        user = self.user_manager.authenticate_user(req.userid, req.passwd)

        if user is None:
            # Unknown id or wrong password. Only an unknown id may be registered.
            if not self.configuration.allow_wfc_registration_through_login or not is_valid_user_id(req.userid):
                return nas_response(NasReturnCode.USER_NOT_FOUND)

            user = self.user_manager.register_user(req.userid, req.passwd)
            if user is None:
                return nas_response(NasReturnCode.USER_NOT_FOUND)

            logger.info("Created account for user %s", user.redacted_id)

        token, challenge = self.user_manager.create_service_session(user, GAMESPY_SERVICE, req.gsbrcd)
        logger.info("Created GameSpy session for user %s", user.redacted_id)
        return nas_response(locator="gamespy.com", token=token, challenge=challenge)

    def handle_create_account(self, req: NasRequest) -> ResponseReturnValue:
        """Register a new WFC account."""
        user = self.user_manager.register_user(req.userid, req.passwd) if is_valid_user_id(req.userid) else None

        if user is None:
            return nas_response(NasReturnCode.USER_ALREADY_EXISTS)

        logger.info("Created account for user %s", user.redacted_id)
        return nas_response(NasReturnCode.REGISTRATION_SUCCESS)

    def handle_retrieve_service_location(self, req: NasRequest) -> ResponseReturnValue:
        """Start a session for the Global Link or the download server."""
        user = self.user_manager.authenticate_user(req.userid, req.passwd)

        if user is None:
            return nas_response(NasReturnCode.USER_NOT_FOUND)

        if req.svc not in SERVICES:
            logger.error("Invalid NAS service type: %s", req.svc)
            return nas_response(NasReturnCode.BAD_REQUEST)

        service, label = SERVICES[req.svc]
        token, _ = self.user_manager.create_service_session(user, service)
        logger.info("Created %s session for user %s", label, user.redacted_id)
        return nas_response(statusdata="Y", svchost=service, servicetoken=token)
