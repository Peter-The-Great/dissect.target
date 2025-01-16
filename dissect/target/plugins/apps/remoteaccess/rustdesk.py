import re
import logging
from datetime import datetime
from typing import Iterator

from dissect.target.exceptions import UnsupportedPluginError
from dissect.target.helpers.descriptor_extensions import UserRecordDescriptorExtension
from dissect.target.helpers.fsutil import TargetPath
from dissect.target.helpers.record import create_extended_descriptor
from dissect.target.plugin import export
from dissect.target.plugins.apps.remoteaccess.remoteaccess import (
    GENERIC_LOG_RECORD_FIELDS,
    RemoteAccessPlugin,
)
from dissect.target.plugins.general.users import UserDetails
log = logging.getLogger(__name__)

class RustdeskPlugin(RemoteAccessPlugin):
    """Rustdesk plugin."""

    __namespace__ = "rustdesk"


    RemoteAccessLogRecord = create_extended_descriptor([UserRecordDescriptorExtension])(
        "remoteaccess/restdesk/log", GENERIC_LOG_RECORD_FIELDS
    )

    # Rustdesk logs when installed as a service/server
    SERVER_GLOBS = [
        # Windows >= Windows 7
        "sysvol/Windows/ServiceProfiles/LocalService/AppData/Roaming/RustDesk/log/server/*.log",

        # Linux
        "var/log/rustdesk-server/*.log",

        # Mac
        "Library/Logs/RustDesk/server/*.log",
    ]

    # User specific Rustdesk logs
    USER_GLOBS = [
        # Windows
        "AppData/Roaming/Rustdesk/log/*.log",

        # Linux
        ".local/share/logs/RustDesk/server/*.log",

        # Android
        "/storage/emulated/0/RustDesk/logs/*.log",

        # Mac
        "Library/Logs/RustDesk/*.log",
    ]


    def __init__(self, target):
        super().__init__(target)

        self.log_files: set[tuple[TargetPath, UserDetails]] = set()

        # Service globs
        user = None
        for log_glob in self.SERVER_GLOBS:
            for log_file in self.target.fs.path().glob(log_glob):
                self.log_files.add((log_file, user))

        # User globs
        for user_details in self.target.user_details.all_with_home():
            for log_glob in self.USER_GLOBS:
                for log_file in user_details.home_path.glob(log_glob):
                    self.log_files.add((log_file, user_details.user))

    def check_compatible(self) -> None:
        if not self.log_files:
            raise UnsupportedPluginError("No Rustdesk log files found on target")
    
    @export(record=RemoteAccessLogRecord)
    def logs(self) -> Iterator[RemoteAccessLogRecord]:
        """Parse Rustdesk log files.

        Rustdesk is remote access software that allows users to connect to a remote computer.
        The project is open source and can be found at: https://github.com/rustdesk/rustdesk/

        The log files are stored in different locations, based on the Target OS and client type.
        Unlike Anydesk, Rustdesk does have a carry a time zone designator (TZD).

        Refrences:
            - https://rustdesk.com/docs/en/self-host/rustdesk-server-pro/faq
            - https://www.reddit.com/r/rustdesk/comments/1072zst/going_to_need_to_know_where_the_client_installer/
            - https://github.com/IRB0T/Remote-Access-Tools---4N6/blob/main/RustDesk/README.md
            - https://github.com/rustdesk/rustdesk/wiki/FAQ#access-logs
        """
        for log_file, user in self.log_files:
            for line in log_file.open("rt", errors="backslashreplace"):
                line = line.strip()

                try:
                    # Still needs to be checked for Rustdesk implementation
                    match = re.match(r"\[(.*?)\] (\w+) \[(.*?)\] (.*)", line)
                    if not match:
                        raise ValueError("Line does not match expected format")

                    ts, level, source, message = match.groups()

                    timestamp = datetime.fromisoformat(ts)
                    message = re.sub(r"\s\s+", " ", f"{level} {source} {message}")

                    yield self.RemoteAccessLogRecord(
                        ts=timestamp,
                        message=message,
                        source=log_file,
                        _target=self.target,
                        _user=user,
                    )

                except ValueError as e:
                    self.target.log.warning("Could not parse log line in file %s: '%s'", log_file, line)
                    self.target.log.debug("", exc_info=e)