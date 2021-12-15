""""""

import asyncio
import datetime
import json
import logging
import os
import time
from argparse import ArgumentParser

from pyvmtivo.client import Client
from pyvmtivo.exceptions import (
    VirginMediaError,
    VirginMediaInvalidChannel,
    VirginMediaNotLive,
)

from pyvmtvguide.api import API

_LOGGER = logging.getLogger("pyvmtvguide.cli")


def _setup_args(parser: ArgumentParser) -> None:
    """Initialise the arguments for the CLI"""

    parser.add_argument("-v", "--verbose", action="count", default=0, help="Set verbosity level")

    sub_parsers = parser.add_subparsers(
        dest="target",
        title="Targets",
        description="Actions to carry out",
        help="Select one of these actions"
    )

    parser_guide = sub_parsers.add_parser("guide", help="")
    parser_tivo = sub_parsers.add_parser("tivo", help="")

    parser_tivo.add_argument("-a", "--address", required=True, help="Address of the V6")
    parser_tivo.add_argument("-t", "--timeout", type=float, default=1, help="Set the connection timeout")

    parser_guide.add_argument("-p", "--password", type=str, required=True, help="Virgin Media password")
    parser_guide.add_argument("-u", "--username", type=str, required=True, help="Virgin Media username")

    sub_parsers_guide = parser_guide.add_subparsers(dest="target_guide")
    sub_parsers_tivo = parser_tivo.add_subparsers(dest="target_tivo")

    parser_channels = sub_parsers_guide.add_parser("channels", help="Log output from the session")
    parser_channels.add_argument("-c", "--cache-file", type=str, required=True, help="Cache file")

    parser_listings = sub_parsers_guide.add_parser("listings", help="Log output from the session")
    parser_listings.add_argument("-c", "--channel-id", type=str, required=True, help="Channel ID")
    parser_listings.add_argument("-d", "--duration", type=int, default=24, help="Hours of listings to retrieve")
    parser_listings.add_argument("-l", "--location-id", type=int, required=False, help="Location ID")

    parser_set_channel = sub_parsers_tivo.add_parser("setchannel", help="Set the channel on the V6")
    parser_set_channel.add_argument("-n", "--channel-number", type=int, required=True, help="Channel number")


async def main():
    """"""

    # region #-- handle arguments --#
    args_parser = ArgumentParser(prog="pyvmtvguide")
    _setup_args(parser=args_parser)
    args = args_parser.parse_args()
    # endregion

    # region #-- setup logging --#
    logging.basicConfig()
    if args.verbose == 0:
        _LOGGER.setLevel(logging.INFO)
    if args.verbose > 0:
        _LOGGER.setLevel(logging.DEBUG)
    if args.verbose > 1:
        logging.getLogger("pyvmtvguide.api").setLevel(logging.DEBUG)
        logging.getLogger("pyvmtivo.client").setLevel(logging.DEBUG)
    # endregion

    if args.target.lower() == "guide":
        if args.target_guide.lower() == "channels":
            async def _async_get_channels_from_api(cache_session=None):
                """"""

                _LOGGER.debug("Loading channels from API")
                async with API(username=args.username, password=args.password, existing_session=cache_session) as api:
                    await api.async_login()
                    api_channels = await api.async_get_channels()
                    api_channels["auth_session"] = api.session_details
                    with open(args.cache_file, "w") as cache_file:
                        json.dump(api_channels, cache_file, indent=2)

            def _load_channels_from_cache() -> dict:
                """"""

                _LOGGER.debug("Loading channels from the cache")
                with open(args.cache_file, "r") as cache_file:
                    cached_channels = json.load(cache_file)
                return cached_channels

            if not os.path.exists(args.cache_file):
                await _async_get_channels_from_api()
                channels = _load_channels_from_cache()
            else:
                channels = _load_channels_from_cache()
                # region #-- update the cache if we need to --#
                _LOGGER.debug("Checking if we need to update the cache")
                last_updated = channels.get("updated") / 1000
                current_epoch = int(time.mktime(datetime.datetime.now().timetuple()))
                update_interval = 24
                update_at = last_updated + (update_interval * 60 * 60)
                if update_at < current_epoch:
                    _LOGGER.debug(f"Cache is stale by {int(current_epoch - update_at)} seconds")
                    await _async_get_channels_from_api()
                    channels = _load_channels_from_cache()
                else:
                    _LOGGER.debug(f"Cache is still good for {int(update_at - current_epoch)} seconds")
                # endregion

            source_list = [
                f"{channel.get('channelNumber')}: {channel.get('title')}"
                for channel in channels.get("channels", [])
            ]
            _LOGGER.info(source_list)
        elif args.target_guide.lower() == "listings":
            async with API(username=args.username, password=args.password) as api:
                listings = await api.async_get_listing(
                    location_id=args.location_id,
                    channel_id=args.channel_id,
                    start_time=int(time.mktime(datetime.datetime.now().timetuple())),
                    duration_hours=args.duration,
                )
            _LOGGER.info(json.dumps(listings))
    elif args.target.lower() == "tivo":
        if args.target_tivo.lower() == "setchannel":
            _LOGGER.info("Setting channel")
            async with Client(host=args.address, timeout=args.timeout) as v6:
                try:
                    await v6.set_channel(channel_number=args.channel_number)
                except (VirginMediaError, VirginMediaInvalidChannel, VirginMediaNotLive) as e:
                    _LOGGER.error(e)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt as err:
        _LOGGER.debug("User exited the CLI")
    else:
        _LOGGER.debug("CLI exited")
