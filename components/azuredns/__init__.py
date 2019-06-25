"""Support for Azure DNS services."""
import logging

from datetime import datetime
from datetime import timedelta

import adal
import voluptuous as vol
import aiohttp

from azure.mgmt.dns import DnsManagementClient
from msrestazure.azure_active_directory import AdalAuthentication
from msrestazure.azure_cloud import AZURE_PUBLIC_CLOUD
from msrestazure.azure_exceptions import CloudError

import homeassistant.helpers.config_validation as cv
from homeassistant.const import CONF_HOST, CONF_DOMAIN
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'azuredns'
RECORDTYPE = 'A'

INTERVAL = timedelta(minutes=5)

LOGIN_ENDPOINT = AZURE_PUBLIC_CLOUD.endpoints.active_directory
RESOURCE = AZURE_PUBLIC_CLOUD.endpoints.active_directory_resource_id

CONF_CLIENTID = 'clientid'
CONF_CLIENTSECRET = 'clientsecret'
CONF_TENANT = 'tenant'
CONF_SUBSCRIPTIONID = 'subscriptionid'
CONF_RESOURCEGROUPNAME = 'resourcegroupname'
CONF_TTL = 'ttl'
CONF_TIMEOUT = 'timeout'

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_DOMAIN): cv.string,
        vol.Optional(CONF_HOST, default='@'): cv.string,
        vol.Required(CONF_TENANT): cv.string,
        vol.Required(CONF_CLIENTID): cv.string,
        vol.Required(CONF_CLIENTSECRET): cv.string,
        vol.Required(CONF_SUBSCRIPTIONID): cv.string,
        vol.Required(CONF_RESOURCEGROUPNAME): cv.string,
        vol.Optional(CONF_TIMEOUT, default=60): cv.positive_int,
        vol.Optional(CONF_TTL, default=60): cv.positive_int
    })
}, extra=vol.ALLOW_EXTRA)


async def async_setup(hass, config):
    """Initialize the Azure DNS component."""

    # Acquire the Azure AD token.
    try:
        context = adal.AuthenticationContext(
            LOGIN_ENDPOINT + '/' + config[DOMAIN][CONF_TENANT])

        credentials = AdalAuthentication(
            context.acquire_token_with_client_credentials,
            RESOURCE,
            config[DOMAIN][CONF_CLIENTID],
            config[DOMAIN][CONF_CLIENTSECRET]
        )

    except adal.AdalError as error:
        _LOGGER.error("Failed to acquire Azure AD Credential: %s", error)
        return False

    result = await _update_azuredns(config, credentials)

    if not result:
        _LOGGER.error("Failed to update Azure DNS record")
        return False

    async def update_domain_interval():
        """Update the Azure DNS entry."""
        await _update_azuredns(config, credentials)

    async_track_time_interval(hass, update_domain_interval, INTERVAL)
    return result


async def _update_azuredns(config, credentials):
    """Update the Azure DNS Record with the external IP address."""
    # Get the external IP address of the Home Assistant instance.
    aiotimeout = aiohttp.ClientTimeout(total=config[DOMAIN][CONF_TIMEOUT])

    async with aiohttp.ClientSession(timeout=aiotimeout) as aiosession:
        async with aiosession.get('https://api.ipify.org') as aioresp:
            ipv4address = (await aioresp.text())

    if not ipv4address:
        _LOGGER.error("Failed to get external IP address from ipify API")
    else:
        _LOGGER.debug("External IP address is: %s", ipv4address)

    # Create the request.
    dns_client = DnsManagementClient(
        credentials,
        config[DOMAIN][CONF_SUBSCRIPTIONID]
    )

    try:
        dns_client.record_sets.create_or_update(
            config[DOMAIN][CONF_RESOURCEGROUPNAME],
            config[DOMAIN][CONF_DOMAIN],
            config[DOMAIN][CONF_HOST],
            RECORDTYPE,
            {
                "metadata": {
                    "Last_changed_by_Home_Assistant": str(datetime.now())
                },
                "ttl": config[DOMAIN][CONF_TTL],
                "arecords": [
                    {
                        "ipv4_address": ipv4address
                    }
                ]
            }
        )
    except CloudError as error:
        _LOGGER.error("Failed to create or update DNS record: %s", error)
        return False

    return True
