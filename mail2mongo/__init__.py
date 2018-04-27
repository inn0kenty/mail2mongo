"""
Simple SMTP daemon which save incoming emails to MongoDB

Author: Innokenty Lebedev <innlebedev@protonmail.com>
"""

# pylint: disable=missing-docstring

import json
import asyncio
import argparse
import logging
from functools import partial
from collections import namedtuple
from datetime import datetime, timezone
from aiosmtpd.controller import Controller
from aiosmtpd.handlers import AsyncMessage
from aiohttp import web, WSMsgType
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from pymongo.errors import PyMongoError

__version__ = '0.3.3'

LOG = logging.getLogger('mail2mongo')

class JSONEncoder(json.JSONEncoder):
    def default(self, o):  # pylint: disable=method-hidden
        if isinstance(o, ObjectId):
            return str(o)
        elif isinstance(o, datetime):
            # ISO-8601
            return o.isoformat()
        return super().default(o)

dumps = partial(json.dumps, cls=JSONEncoder)  # pylint: disable=invalid-name

class MessageHandler(AsyncMessage):
    def __init__(self, ws_conn, mongo, app_tasks, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ws_conn = ws_conn
        self._mongo = mongo
        self._app_tasks = app_tasks

    async def process_payload(self, payload):
        sleep_time = 60  # seconds
        while True:
            try:
                await self._mongo.insert_one(payload)
                break
            except PyMongoError as exc:
                LOG.error(exc)
                LOG.error(payload)
                LOG.error('Retry after %s seconds', sleep_time)
                await asyncio.sleep(sleep_time)
                sleep_time = 2 * sleep_time

        websock = self._ws_conn.get(payload['to'])
        if websock is not None:
            await websock.send_json(
                dict(type='new_mail', payload=payload),
                dumps=dumps
            )

    async def handle_message(self, message):
        payload = {
            'from': message.get('From', ''),
            'to': message.get('To', ''),
            'subject': message.get('Subject', ''),
            'timestamp': datetime.now(timezone.utc)
        }

        if message.is_multipart():
            for msg in message.get_payload():
                if msg.get_content_type() == 'text/plain':
                    payload['text'] = msg.get_payload()
                    break
            else:
                LOG.error(
                    'Message without text/plain:\n%s\n\n%s\n',
                    payload,
                    message.as_string()
                )
                return
        else:
            payload['text'] = message.get_payload()

        payload['text'] = (payload['text']
                           .strip()
                           .strip('\n')
                           .strip('\r')
                           .strip())

        fut = asyncio.ensure_future(
            self.process_payload(payload),
            loop=self.loop
        )
        self._app_tasks.append(fut)
        fut.add_done_callback(self._app_tasks.remove)


class SMTPController(Controller):
    async def start(self):
        self.server = await self.loop.create_server(
            self.factory, host=self.hostname, port=self.port,
            ssl=self.ssl_context
        )

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

class Application(object):  # pylint: disable=too-many-instance-attributes
    def __init__(self, config):
        self._ws_conn = {}
        self._loop = asyncio.get_event_loop()
        self._allow_domains = config.domains
        self._smtp_port = config.smtp_port
        self._api_port = config.api_port
        self._mongo = AsyncIOMotorClient(
            config.mongo_uri,
            io_loop=self._loop,
            socketTimeoutMS=3000,
            connectTimeoutMS=3000,
            serverSelectionTimeoutMS=3000
        )
        self._app_tasks = []
        self._smtp_controller = SMTPController(
            MessageHandler(
                self._ws_conn,
                self._mongo[config.db_name][config.col_name],
                self._app_tasks,
                loop=self._loop
            ),
            hostname='0.0.0.0',
            port=self._smtp_port,
            loop=self._loop
        )

    async def stop(self, _):
        await self._smtp_controller.stop()

        for task in self._app_tasks:
            task.cancel()

        await asyncio.gather(
            *self._app_tasks,
            loop=self._loop,
            return_exceptions=True
        )

        ws_closers = [
            websock.close() for _, websock in self._ws_conn.items()
            if not websock.closed
        ]

        if ws_closers:
            await asyncio.gather(*ws_closers, loop=self._loop)

        self._mongo.close()

    async def websocket_handler(self, request):
        websock = web.WebSocketResponse()
        await websock.prepare(request)

        if 'email' not in request.query:
            await websock.send_json(
                dict(type='error', payload={'msg': 'email should be defined'})
            )
            await websock.close()
            return websock

        if request.query['email'] in self._ws_conn:
            await websock.send_json(
                dict(type='error', payload={'msg': 'subscriber already exists'})
            )
            await websock.close()
            return websock

        self._ws_conn[request.query['email']] = websock

        try:
            async for msg in websock:
                if msg.type == WSMsgType.CLOSE:
                    await websock.close()
        finally:
            del self._ws_conn[request.query['email']]

        return websock

    async def auth_handler(self, request):
        rcpt = request.headers.get('Auth-SMTP-To', '')
        rcpt = rcpt.split('<')[1].split('>')[0].split('@')[1]

        check_passed = [x for x in self._allow_domains if x == rcpt]
        if not check_passed:
            response = {
                'Auth-Status': 'FORBIDDEN',
                'Auth-Wait': '0'
            }
        else:
            response = {
                'Auth-Status': 'OK',
                'Auth-Server': request.headers['Host'],
                'Auth-Port': str(self._smtp_port)
            }

        return web.Response(status=200, headers=response)

    async def app_factory(self):
        await self._smtp_controller.start()

        app = web.Application()
        app.on_shutdown.append(self.stop)
        app.add_routes(
            [
                web.get('/ws', self.websocket_handler),
                web.get('/nginx-auth', self.auth_handler)
            ]
        )

        return app

    def run(self):
        web.run_app(self.app_factory(), host='0.0.0.0', port=self._api_port)

Config = namedtuple(
    'Config',
    [
        'domains',
        'smtp_port',
        'api_port',
        'mongo_uri',
        'db_name',
        'col_name'
    ]
)

def parse_args():
    parser = argparse.ArgumentParser(
        description='Save incoming emails to mongodb',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('-m', '--mongo', dest='mongo_uri', type=str,
                        help='Mongo URI', default='mongodb://localhost')
    parser.add_argument('-db', '--db-name', dest='db_name', type=str,
                        help='Mongo data base', default='mail2mongo')
    parser.add_argument('-cn', '--col-name', dest='col_name', type=str,
                        help='Mongo collection name', default='emails')
    parser.add_argument('-ap', '--api-port', dest='api_port', type=int,
                        help='API port', default=8080)
    parser.add_argument('-sp', '--smtp-port', dest='smtp_port', type=int,
                        help='SMTPD port', default=8025)
    parser.add_argument('-d', '--domains', dest='domains', type=str, nargs='+',
                        required=True, help='Allowed domains', default=[])
    namespace = parser.parse_known_args()

    config = Config(
        mongo_uri=namespace[0].mongo_uri,
        db_name=namespace[0].db_name,
        col_name=namespace[0].col_name,
        api_port=namespace[0].api_port,
        smtp_port=namespace[0].smtp_port,
        domains=namespace[0].domains
    )

    return config

def entrypoint():
    logging.basicConfig(level=logging.INFO)
    Application(parse_args()).run()

if __name__ == '__main__':
    entrypoint()
