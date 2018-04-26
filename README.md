# Info

Simple SMTP daemon which can save incoming emails to MongoDB and send it to WebSocket.

You should own domain name, MX record and nginx.

# Install

```bash
$ pip3 install mail2mongo
```

## Run

```bash
$ mail2mongo --help
usage: main.py [-h] [-m MONGO_URI] [-db DB_NAME] [-cn COL_NAME] [-ap API_PORT]
               [-sp SMTP_PORT] -d DOMAINS [DOMAINS ...]

Save incoming emails to mongodb

optional arguments:
  -h, --help            show this help message and exit
  -m MONGO_URI, --mongo MONGO_URI
                        Mongo URI (default: mongodb://localhost)
  -db DB_NAME, --db-name DB_NAME
                        Mongo data base (default: mail2mongo)
  -cn COL_NAME, --col-name COL_NAME
                        Mongo collection name (default: emails)
  -ap API_PORT, --api-port API_PORT
                        API port (default: 8080)
  -sp SMTP_PORT, --smtp-port SMTP_PORT
                        SMTPD port (default: 8025)
  -d DOMAINS [DOMAINS ...], --domains DOMAINS [DOMAINS ...]
                        Allowed domains (default: [])
```

Argument `-d/--domains` required! It's a domain names list which you own.

From python package

```bash
$ mail2mongo -d example.com -m mongodb://192.168.0.100:27017
```

From Docker image

```bash
$ docker run -p 8080:8080 -p 8025:8025 inn0kenty/mail2mongo -d example.com -m mongodb://192.168.0.100:27017
```

## nginx

File `/etc/nginx/nginx.conf` should contains:

```
mail {
    server_name <Your MX record>;

    auth_http <local ip:port>/nginx-auth;

    proxy_pass_error_message off;

    server {
        listen 25;
        protocol smtp;
        proxy on;
        smtp_auth none;
        xclient off;
    }
}
```

The MX record usually has the form `mail.example.com` where `example.com` your domain name. The `mail.example.com` must be resolved to your ip address.

Local ip:port - local ip address and port (api_port, default 8080).

## WebSocket

You can use WebSocket on `/ws` url. Also you should provide email address.

Example

```python
import asyncio
import aiohttp


async def main():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect('ws://127.0.0.1:8080/ws?email=foo@example.com') as ws:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    print(msg.json())
                else:
                    break

loop = asyncio.get_event_loop()
loop.run_until_complete(main())
```

You can get messages of two types:

If something go wrong:

```
{'type': 'error', 'payload': {'msg': 'Error message'}}
```

If you receive new email:

```
{'type': 'new_mail', 'payload': {'from': 'root@google.com', 'to': 'foo@example.com', 'subject': 'Foo bar', 'text': 'Some message', 'timestamp': '1970-01-01T00:00:00.000000+00:00', '_id': '5ae0988c754ea76f22935378'}}
```

`_id` - `ObjectId` in MongoDB.

Similar payload saved to MongoDB.

If for some reason MongoDB is down, service will continue try to save payload to mongo. At each next step service will be double sleep time (default is 60 seconds).

