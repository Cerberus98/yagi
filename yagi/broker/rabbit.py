import json
import time

import carrot.connection
import carrot.messaging

from yagi import config as conf
import yagi.log

with conf.defaults_for('rabbit_broker') as default:
    default('host', 'localhost')
    default('user', 'guest')
    default('password', 'guest')
    default('port', 5672)
    default('vhost', '/')
    default('poll_delay', 1)

LOG = yagi.log.logger

class Broker(object):
    def __init__(self):
        self.callbacks = []
        config = conf.config_with('rabbit_broker')
        self.conn = carrot.connection.BrokerConnection(
                hostname=config('host'),
                port=5672,
                userid=config('user'),
                password=config('password'),
                virtual_host=config('vhost'))
        self.consumers = []

    def add_consumer(self, consumer):
        self.consumers.append((consumer.config('max_messages'),
            carrot.messaging.Consumer(
                connection=self.conn,
                warn_if_exists=True,
                exchange=consumer.config('exchange'),
                exchange_type=consumer.config('exchange_type'),
                routing_key = consumer.config('routing_key'),
                queue=consumer.queue_name,
                durable=consumer.config('durable'))))
        self.callbacks.append(consumer.fetched_messages)

    def trigger_callbacks(self, messages):
        for callback in self.callbacks:
            callback(messages)

    def loop(self):
        LOG.debug('Starting Carrot message loop')
        poll_delay = float(conf.get('rabbit_broker', 'poll_delay'))
        while True:
            for count, consumer in self.consumers:
                messages = []
                for n in xrange(count):
                    msg = consumer.fetch(enable_callbacks=False)
                    if not msg:
                        break
                    try:
                        messages.append(json.loads(msg.payload))
                    except Exception, e:
                        LOG.error('Message decoding failed!')
                        continue
                    LOG.debug('Received message on queue %s' % level)
                    if not msg.acknowledged:
                        msg.ack()
                self.trigger_callbacks(messages)
            time.sleep(poll_delay)

