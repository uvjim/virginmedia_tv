"""API details for the TV guide."""

# region #-- imports --#
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
import bs4.element
from bs4 import BeautifulSoup

from .const import (
    DEF_SCHEDULES_MAX,
    DEF_URL_AUTH,
    DEF_URL_CHANNELS,
    DEF_URL_LOGIN,
    DEF_URL_SCHEDULES,
    DEF_URL_SESSION,
)
from .exceptions import (
    VirginMediaTVGuideError,
    VirginMediaTVGuideForbidden,
    VirginMediaTVGuideUnauthorized,
)
from .logger import Logger

# endregion

_LOGGER = logging.getLogger(__name__)


class API:
    """Virgin Media TV Guide API."""

    def __init__(self, username: str, password: str, existing_session=None) -> None:
        """Initialise."""
        if existing_session is None:
            existing_session = {}

        self._auth_code: str = ""
        self._auth_refresh_token: str = ""
        self._auth_session: dict = existing_session
        self._auth_state: str = ""
        self._auth_uri: str = ""
        self._auth_username: str = ""
        self._auth_validity_token: str = ""
        self._log_formatter: Logger = Logger()
        self._login_redirect: str = ""
        self._password: str = password
        self._session: Optional[aiohttp.ClientSession] = None
        self._username: str = username

    async def __aenter__(self) -> "API":
        """Entry point for the Context Manager."""
        self._create_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit point for the Context Manager."""
        await self._async_close_session()

    # region #-- private methods --#
    def _create_session(self) -> None:
        """Initialise the client session."""
        _LOGGER.debug(self._log_formatter.format("entered"))
        self._session = aiohttp.ClientSession(raise_for_status=True)
        _LOGGER.debug(self._log_formatter.format("exited"))

    async def _async_close_session(self) -> None:
        """Close the client session."""
        _LOGGER.debug(self._log_formatter.format("entered"))
        await self._session.close()
        _LOGGER.debug(self._log_formatter.format("exited"))

    async def _async_get_request(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Issue a GET request to the online service.

        Additional arguments are passed onto the underlying GET request

        :param url: Location to send the request
        :param kwargs: additional arguments
        :return: the reponse as it was receieved
        """
        _LOGGER.debug(
            self._log_formatter.format("entered, url: %s, kwargs: %s"), url, kwargs
        )
        try:
            resp: aiohttp.ClientResponse = await self._session.get(
                url, allow_redirects=False, **kwargs
            )
        except aiohttp.ClientError:
            raise
        except Exception as err:
            raise VirginMediaTVGuideError(err) from None
        else:
            if resp.status in (200, 302):
                return resp
        _LOGGER.debug(self._log_formatter.format("exited"))

    async def _async_get_auth_code(self) -> None:
        """Retrieve an auth code."""
        _LOGGER.debug(self._log_formatter.format("Step 4 --> entered"))
        try:
            resp = await self._async_get_request(url=self._login_redirect)
        except Exception as err:
            raise VirginMediaTVGuideError(err) from None
        else:
            self._auth_code = resp.headers.get("location")
            code_matches = re.findall(r"code=(.*)&", self._auth_code)
            if len(code_matches) != 1:
                raise ValueError
            self._auth_code = code_matches[0]
        _LOGGER.debug(self._log_formatter.format("Step 4 --> exited"))

    async def _async_get_auth_cookie(self) -> None:
        """Retrieve a cookie for authorisation."""
        _LOGGER.debug(self._log_formatter.format("Step 2 --> entered"))
        try:
            await self._async_get_request(url=self._auth_uri)
        except Exception as err:
            raise VirginMediaTVGuideError(err) from None
        _LOGGER.debug(self._log_formatter.format("Step 2 --> exited"))

    async def _async_get_auth_details(self) -> None:
        """Get the initial details about where to go."""
        _LOGGER.debug(self._log_formatter.format("Step 1 --> entered"))
        try:
            resp = await self._async_get_request(url=DEF_URL_AUTH)
            resp_json = await resp.json()
        except Exception as err:
            raise VirginMediaTVGuideError(err) from None
        else:
            self._auth_state = resp_json.get("session", {}).get("state")
            self._auth_uri = resp_json.get("session", {}).get("authorizationUri")
            self._auth_validity_token = resp_json.get("session", {}).get(
                "validityToken"
            )
        _LOGGER.debug(self._log_formatter.format("Step 1 --> exited"))

    async def _async_get_oesp_code(self) -> None:
        """Get the codes we'll need later."""
        _LOGGER.debug(self._log_formatter.format("Step 6 --> entered"))
        try:
            resp = await self._async_post_request(
                url=DEF_URL_SESSION,
                json={
                    "refreshToken": self._auth_refresh_token,
                    "username": self._auth_username,
                },
                params={"token": "true"},
            )
            resp_json = await resp.json()
        except Exception as err:
            raise VirginMediaTVGuideError(err) from None
        else:
            self._auth_session = resp_json
        _LOGGER.debug(self._log_formatter.format("Step 6 --> exited"))

    async def _async_login(self) -> None:
        """Send the service credentials."""
        _LOGGER.debug(self._log_formatter.format("Step 3 --> entered"))
        try:
            resp: aiohttp.ClientResponse = await self._async_post_request(
                url=DEF_URL_LOGIN,
                json={
                    "username": self._username,
                    "credential": self._password,
                },
                headers={"accept": "*/*"},
            )
        except Exception as err:
            raise VirginMediaTVGuideError(err) from None
        else:
            self._login_redirect = resp.headers.get("x-redirect-location")
        _LOGGER.debug(self._log_formatter.format("Step 3 --> exited"))

    async def _async_post_request(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Send a POST request.

        Additional arguments are passed onto the underlying POST request

        :param url: Location to send the request
        :param kwargs: Additional arguments
        :return: the response as it was received
        """
        try:
            resp: aiohttp.ClientResponse = await self._session.post(
                url, allow_redirects=False, **kwargs
            )
        except aiohttp.ClientError as err:
            raise VirginMediaTVGuideUnauthorized(err) from None
        else:
            if resp.status == 200:
                return resp

    async def _async_reauthorize(self) -> None:
        """Reauthorise with the additional information."""
        _LOGGER.debug(self._log_formatter.format("Step 5 --> entered"))
        try:
            resp = await self._async_post_request(
                url=DEF_URL_AUTH,
                json={
                    "authorizationGrant": {
                        "authorizationCode": self._auth_code,
                        "state": self._auth_state,
                        "validityToken": self._auth_validity_token,
                    }
                },
            )
            resp_json = await resp.json()
        except Exception as err:
            raise VirginMediaTVGuideError(err) from None
        else:
            self._auth_refresh_token = resp_json.get("refreshToken", "")
            self._auth_username = resp_json.get("username", "")
        _LOGGER.debug(self._log_formatter.format("Step 5 --> exited"))

    # endregion

    # region #-- public methods --#
    async def async_get_channels(self) -> dict:
        """Get the channels from the online service.

        The location previously retrieved is used to ensure the returned channels are
        those available for your region.

        If the first attempt fails for a Forbidden reason we'll log in again, the stored
        session could have expired. I haven't worked out the reauth flow, so we'll just
        do the whole login again.

        :return: an object containing all the channels as they were returned
        """
        _LOGGER.debug(self._log_formatter.format("entered"))
        if not self._auth_session:
            await self.async_login()

        ret: dict = {}
        attempts: int = 1
        while not ret and attempts <= 2:
            try:
                resp = await self._async_get_request(
                    url=DEF_URL_CHANNELS,
                    headers={
                        "X-OESP-Token": self._auth_session.get("oespToken", ""),
                        "X-OESP-Username": self._auth_session.get("username", ""),
                    },
                    params={
                        "byLocationId": self._auth_session.get("locationId", ""),
                        "includeInvisible": "true",
                        "includeNotEntitled": "false",
                        "personalised": "true",
                        "sort": "channelNumber",
                    },
                )
                resp_json = await resp.json()
            except aiohttp.ClientResponseError as err:
                if err.status != 403:
                    raise VirginMediaTVGuideError(err) from None

                if attempts >= 2:
                    raise VirginMediaTVGuideForbidden from None
                else:
                    await self.async_login()
                    attempts += 1
            except Exception as err:
                raise VirginMediaTVGuideError(err) from None
            else:
                ret = resp_json

        _LOGGER.debug(self._log_formatter.format("exited"))
        return ret

    async def async_get_listing(
        self,
        channel_id: str,
        start_time: int,
        duration_hours: int,
        location_id: Optional[int] = None,
    ) -> Optional[dict]:
        """Get the listing for a particular channel.

        :param channel_id: the ID of the channel to retrieve info for (station_id in the original return)
        :param start_time: when to retrieve the listings from
        :param duration_hours: how long to retrieve the listings for (in hours)
        :param location_id: location (will use the location from login if it is available)
        :return: object containing all the listings as returned by the service
        """
        _LOGGER.debug(self._log_formatter.format("entered"))

        if not self._auth_session:
            await self.async_login()

        if not location_id:
            _LOGGER.debug(self._log_formatter.format("using stored location ID"))
            location_id = self._auth_session.get("locationId")

        ret = None
        try:
            resp = await self._async_get_request(
                url=f"{DEF_URL_SCHEDULES}",
                params={
                    "byLocationId": location_id,
                    "byStationId": channel_id,
                    "byEndTime": f"{start_time * 1000}~{(start_time + (duration_hours * 60 * 60)) * 1000}",
                    "sort": "startTime|asc",
                    "range": f"1-{DEF_SCHEDULES_MAX}",
                },
            )
            resp_json = await resp.json()
        except Exception as err:
            raise VirginMediaTVGuideError(err) from None
        else:
            ret = resp_json

        _LOGGER.debug(self._log_formatter.format("exited"))
        return ret

    async def async_login(self) -> None:
        """Carry out a full login."""
        _LOGGER.debug(self._log_formatter.format("entered"))
        if not self._session:
            self._create_session()

        await self._async_get_auth_details()
        await self._async_get_auth_cookie()
        await self._async_login()
        await self._async_get_auth_code()
        await self._async_reauthorize()
        await self._async_get_oesp_code()
        _LOGGER.debug(self._log_formatter.format("exited"))

    # endregion

    # region #-- properties --#
    @property
    def session_details(self) -> Optional[dict]:
        """Return the important parts of the logged-in session."""
        ret = None
        if self._auth_session:
            exportable_properties = (
                "locationId",
                "oespToken",
                "username",
            )
            ret = {
                k: v
                for k, v in self._auth_session.items()
                if k in exportable_properties
            }

        return ret

    # endregion


class TVChannelLists:
    """Get the channel mappings from TV Channel lists.

    Required because the V6 doesn't use the same channel layout as that returned
    by the Virgin Media API
    """

    _CHANNEL_COL_PLATFORMS: List[str] = ["tv 360", "tv v6"]
    _CHANNEL_KEYS: List[str] = ["sd", "hd", "uhd", "+1"]
    _CHANNEL_URL: str = "https://www.tvchannellists.com/w/List_of_channels_on_Virgin_Media_(UK)_-_New_Packages"

    def __init__(self) -> None:
        """Initialise."""
        self._channel_key: dict = {}
        self._log_formatter: Logger = Logger()
        self._session: aiohttp.ClientSession
        self._source: str = ""

    async def __aenter__(self) -> "TVChannelLists":
        """Entry point for the Context Manager."""
        self._create_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit point for the Context Manager."""
        await self._async_close_session()

    # region #-- private methods --#
    def _create_session(self) -> None:
        """Initialise the client session."""
        _LOGGER.debug(self._log_formatter.format("entered"))
        self._session: aiohttp.ClientSession = aiohttp.ClientSession(
            raise_for_status=True
        )
        _LOGGER.debug(self._log_formatter.format("exited"))

    def _get_channel_resolution(self, channel: bs4.element.Tag) -> str:
        """Get the resolution of the channel based on the information given.

        The TV Channel List service uses colours to represent the resoluton.
        These colours are found in the key.

        :param channel: the channel details as returned from the scraped service
        :return: string representing the resolution
        """
        if not self._channel_key:
            self._channel_key = self.channel_key

        channel_colour = channel.attrs.get("bgcolor", "")

        ret: str = ""
        for resolution, colour in self._channel_key.items():
            if channel_colour.lower() == colour.lower():
                return resolution

        return ret

    def _is_col_platform(self, col_name: str) -> bool:
        """Check if the column is a device platform one.

        :param col_name: the name of the column (based on the header)
        :return: True if a device platform, False otherwise
        """
        return col_name in self._CHANNEL_COL_PLATFORMS

    def _table_to_list(self, table: bs4.element.Tag) -> List[Dict[str, Any]]:
        """Convert the given table into a list.

        :param table: the table as it was scraped
        :return: a list of objects representing the values on the rows
        """
        _LOGGER.debug(self._log_formatter.format("entered"))
        ret: list = []

        # region #-- get the column headings --#
        _LOGGER.debug(self._log_formatter.format("retrieving column headings"))
        th_cells: bs4.element.ResultSet = table.find_all("th")
        headings: List[str] = []
        th_cell: bs4.element.Tag
        for th_cell in th_cells:
            headings.append(th_cell.text.strip().lower())
        if len(set(headings).intersection(self._CHANNEL_COL_PLATFORMS)) == 0:
            return ret
        _LOGGER.debug(
            self._log_formatter.format("column headings found: %d"), len(headings)
        )
        # endregion

        # region #-- process the rows --#
        _LOGGER.debug(self._log_formatter.format("processing rows"))
        table_rows: bs4.element.ResultSet = table.find_all("tr")
        row_idx: int
        row_data: bs4.element.Tag
        row_spans: list = []
        for row_idx, row_data in enumerate(table_rows[1:]):
            row_cells: bs4.element.ResultSet = row_data.find_all("td")
            if int(row_cells[0].attrs.get("colspan", 0)):
                _LOGGER.debug(
                    self._log_formatter.format(
                        "skipping row %d - seems to be a divider"
                    ),
                    row_idx,
                )
            else:
                row: dict = {}
                if not row_spans:
                    for col_idx, cell in enumerate(row_cells):
                        if self._is_col_platform(col_name=headings[col_idx]):
                            channel_res = self._get_channel_resolution(channel=cell)
                            if channel_res:
                                row[headings[col_idx]] = {
                                    channel_res: int(cell.text.strip() or 0)
                                }
                        else:
                            row[headings[col_idx]] = cell.text.strip()
                    row_spans = [
                        int(cell.attrs.get("rowspan", 1)) for cell in row_cells
                    ]
                else:
                    cell_counter: int = 0
                    for cell_idx, row_span in enumerate(row_spans):
                        if row_span == 1:
                            cell: bs4.element.Tag = row_cells[cell_counter]
                            if self._is_col_platform(col_name=headings[cell_idx]):
                                channel_res = self._get_channel_resolution(channel=cell)
                                if channel_res:
                                    row[headings[cell_idx]] = {
                                        channel_res: int(cell.text.strip() or 0)
                                    }
                            else:
                                row[headings[cell_idx]] = cell.text.strip()
                            if cell.attrs.get("rowspan"):
                                row_spans[cell_idx] = int(cell.attrs.get("rowspan"))
                            cell_counter += 1
                        else:
                            row[headings[cell_idx]] = ret[-1].get(headings[cell_idx])
                            row_spans[cell_idx] -= 1
                if row:
                    ret.append(row)
        _LOGGER.debug(self._log_formatter.format("processed rows: %d"), len(table_rows))
        # endregion
        _LOGGER.debug(self._log_formatter.format("exited"))

        return ret

    async def _async_close_session(self) -> None:
        """Close the client session."""
        _LOGGER.debug(self._log_formatter.format("entered"))
        await self._session.close()
        _LOGGER.debug(self._log_formatter.format("exited"))

    # endregion

    # region #-- public methods --#
    def load_source(self, source: str) -> None:
        """Load the source.

        This method facilitates loading the source from a local file

        :param source: string containing the source from the online service
        :return: None
        """
        _LOGGER.debug(self._log_formatter.format("entered"))
        self._source = source
        _LOGGER.debug(self._log_formatter.format("exited"))

    async def async_fetch(self) -> None:
        """Retrieve the data from the onine service."""
        _LOGGER.debug(self._log_formatter.format("entered"))
        async with self._session as session:
            resp: aiohttp.ClientResponse = await session.get(url=self._CHANNEL_URL)
            self._source = await resp.text(encoding="utf-8")
        _LOGGER.debug(self._log_formatter.format("exited"))

    # endregion

    # region #-- properties --#
    @property
    def channel_key(self) -> Dict[str, str]:
        """Return the data for the key table."""
        ret = {}

        soup: BeautifulSoup = BeautifulSoup(self._source, "html.parser")
        key_header: bs4.element.Tag = soup.find(id="Key")
        if key_header:
            key_table: bs4.element.Tag = key_header.find_next("table")
            key_row: bs4.element.Tag
            for key_row in key_table.find_all("tr"):
                key_data: bs4.element.Tag = key_row.find("td")
                if key_data and key_data.text.lower().strip() in self._CHANNEL_KEYS:
                    ret[key_data.text.lower().strip()] = key_data.attrs.get(
                        "bgcolor", ""
                    ).lower()

        return ret

    @property
    def channels(self) -> Dict[str, Any]:
        """Process the data for the channels."""
        ret = {}

        soup: BeautifulSoup = BeautifulSoup(self._source, "html.parser")
        channel_start: bs4.element.Tag = soup.find(id="Channel_List")
        if channel_start:
            ret["updated"]: int = int(datetime.now().timestamp()) * 1000
            ret["channels"]: list = []

            channel_tables: bs4.element.ResultSet
            channel_tables = channel_start.find_all_next("table", "wikitable")
            table: bs4.element.Tag
            for table in channel_tables:
                table_as_list: list = self._table_to_list(table=table)
                if table_as_list:
                    ret["channels"].extend(table_as_list)

        return ret

    # endregion
