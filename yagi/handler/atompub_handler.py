import time

import yagi.auth
import yagi.config
import yagi.handler
import yagi.log
import yagi.serializer.atom
from yagi import http_util

with yagi.config.defaults_for("atompub") as default:
    default("validate_ssl", "False")
    default("retries", "0")
    default("url", "http://127.0.0.1/nova")
    default("max_wait", "600")
    default("interval", "30")

LOG = yagi.log.logger


class MessageDeliveryFailed(Exception):
    pass


class AtomPub(yagi.handler.BaseHandler):
    CONFIG_SECTION = "atompub"

    def _send_notification(self, endpoint, puburl, headers, body, conn):
        LOG.debug("Sending message to %s with body: %s" % (endpoint, body))
        headers = {"Content-Type": "application/atom+xml"}
        try:
            resp, content = conn.request(endpoint, "POST",
                                         body=body,
                                         headers=headers)
            if resp.status != 201:
                msg = ("AtomPub resource create failed for %s Status: "
                            "%s, %s" % (puburl, resp.status, content))
                raise Exception(msg)
        except http_util.ResponseTooLargeError, e:
            if e.response.status == 201:
                # Was successfully created. Reply was just too large.
                LOG.error("Response too large on successful post")
                LOG.exception(e)
                # Note that we DON'T want to retry this if we've gotten a 201.
            else:
                raise
        except Exception, e:
            msg = ("AtomPub Delivery Failed to %s with:\n%s" % (endpoint, e))
            raise MessageDeliveryFailed(msg)

    def new_http_connection(self, force=False):
        ssl_check = not bool(self.config_get("validate_ssl"))
        conn = http_util.LimitingBodyHttp(
                            disable_ssl_certificate_validation=ssl_check)
        conn.follow_all_redirects = True
        auth_method = yagi.auth.get_auth_method()
        headers = {}
        if auth_method:
            try:
                auth_method(conn, headers, force=force)
            except Exception, e:
                # Auth could be jacked for some reason, slow down on failing.
                # Alternatively, if we have bad credentials, don't fill
                # up the logs crying about it.
                LOG.exception(e)
                interval = int(self.config_get("interval"))
                time.sleep(interval)
        else:
            raise Exception("Invalid auth or no auth supplied")
        return conn, headers

    def handle_messages(self, message_generator):
        retries = int(self.config_get("retries"))
        interval = int(self.config_get("interval"))
        max_wait = int(self.config_get("max_wait"))
        conn, headers = self.new_http_connection()

        for payload in message_generator():
            try:
                entity = dict(content=payload,
                              id=payload["message_id"],
                              event_type=payload["event_type"])
                payload_body = yagi.serializer.atom.dump_item(entity)
            except KeyError, e:
                LOG.error("Malformed Notification: %s" % payload)
                LOG.exception(e)
                continue

            endpoint = self.config_get("url")
            tries = 0
            while True:
                try:
                    self._send_notification(endpoint, endpoint, headers,
                                            payload_body, conn)
                    break
                except MessageDeliveryFailed, e:
                    LOG.exception(e)

                    # Used primarily for testing, but it's possible we don't
                    # care if we lose messages?
                    if retries:
                        tries += 1
                        if tries >= retries:
                            break
                    wait = min(tries * interval, max_wait)
                    LOG.error("Message delivery failed, going to sleep, will "
                             "try again in %d seconds" % wait)
                    time.sleep(wait)

                    # TODO(cerberus): how did this get isolated? We don't want
                    # to connect every time
                    conn, headers = self.new_http_connection(force=True)
