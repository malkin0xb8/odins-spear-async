import re
import asyncio
from ..exceptions import OSAliasNotFound


def locate_alias(alias, aliases: list):
    if not re.fullmatch(
        r"^[A-Za-z0-9\-_.!~*()']+$", alias
    ):  # As per Odin Spec: User alias cannot contain any characters except A-Z, a-z, 0-9, -_.!~*() or single quotes.
        return False

    for a in aliases:
        if alias == a.split("@")[0]:  # split the string from its alias and domain
            return True
    return False


async def main(api, service_provider_id: str, group_id: str, alias: str):
    RETRY_QUEUE = []
    MAX_RETRIES = 2
    OBJECT_WITH_ALIAS = []

    auto_attendants = await api.auto_attendants.get_auto_attendants(
        service_provider_id, group_id
    )
    hunt_groups = await api.hunt_groups.get_group_hunt_groups(
        service_provider_id, group_id
    )
    call_centers = await api.call_centers.get_group_call_centers(
        service_provider_id, group_id
    )

    # save logger from api
    logger = api.logger

    aa_tasks = [
        (
            "AA",
            aa["serviceUserId"],
            api.auto_attendants.get_auto_attendant(aa["serviceUserId"]),
        )
        for aa in auto_attendants
    ]
    hg_tasks = [
        (
            "HG",
            hg["serviceUserId"],
            api.hunt_groups.get_group_hunt_group(hg["serviceUserId"]),
        )
        for hg in hunt_groups
    ]
    cc_tasks = [
        (
            "CC",
            cc["serviceUserId"],
            api.call_centers.get_group_call_center(cc["serviceUserId"]),
        )
        for cc in call_centers
    ]

    all_tasks = aa_tasks + hg_tasks + cc_tasks

    logger.info(f"Running {len(all_tasks)} async entity fetches...")
    results = await asyncio.gather(
        *(task[2] for task in all_tasks), return_exceptions=True
    )

    # Zip types + results
    for (entity_type, service_user_id, _), result in zip(all_tasks, results):
        if isinstance(result, Exception):
            logger.error(f"Failed to fetch {entity_type} - {service_user_id}: {result}")
            continue

        formatted = {
            "type": entity_type,
            "service_user_id": service_user_id,
            "name": result["serviceInstanceProfile"]["name"],
            "aliases": result["serviceInstanceProfile"]["aliases"],
        }
        OBJECT_WITH_ALIAS.append(formatted)

    while RETRY_QUEUE:
        entity_type, service_user_id, retry_count = RETRY_QUEUE.pop(
            0
        )  # Get the first item from the queue

        formatted = {}
        formatted["type"] = entity_type
        temp_object = ""

        try:
            if entity_type == "AA":
                temp_object = await api.auto_attendants.get_auto_attendant(
                    service_user_id
                )
            elif entity_type == "HG":
                temp_object = await api.hunt_groups.get_group_hunt_group(
                    service_user_id
                )
            else:
                temp_object = await api.call_centers.get_group_call_center(
                    service_user_id
                )

            formatted["name"] = temp_object["serviceInstanceProfile"]["name"]
            formatted["aliases"] = temp_object["serviceInstanceProfile"]["aliases"]

            OBJECT_WITH_ALIAS.append(formatted)

        except Exception:
            if retry_count < MAX_RETRIES:
                RETRY_QUEUE.append(
                    (entity_type, service_user_id, retry_count + 1)
                )  # Increment retry count and re-add to the queue
            else:
                logger.error(
                    f"Failed to process {entity_type} - {service_user_id} after {MAX_RETRIES} retries - skipping"
                )

    logger.info("Searching through aa, hg, and cc")
    for broadwork_entity in OBJECT_WITH_ALIAS:
        logger.info(f"Checking bre '{broadwork_entity['name']}'")
        if locate_alias(alias, broadwork_entity["aliases"]):
            logger.info(
                f"Alias found, type: user, service_user_id: {broadwork_entity['name']}, alias: {alias}"
            )
            return broadwork_entity
    logger.info(f"Alias '{alias}' not found in aa, hg, cc")

    logger.info("Fetching users")
    users = await api.users.get_users(service_provider_id, group_id, extended=True)
    logger.info("Users successfully fetched")

    logger.info("Searching users")
    for user in users:
        logger.info(f"Checking {user['userId']}")
        if locate_alias(alias, user["aliases"]):
            logger.info(
                f"Alias found, type: user, user_id: {user['userId']}, alias: {alias}"
            )
            return {"type": "user", "user_id": user["userId"], "alias": alias}

    return OSAliasNotFound
