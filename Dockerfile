FROM inn0kenty/pyinstaller-alpine:3.6 as build

WORKDIR /build

RUN pip install --no-cache-dir --disable-pip-version-check flit

COPY . .

RUN FLIT_ROOT_INSTALL=1 flit install -s --deps production

ARG PYINSTALLER_ARG
RUN /pyinstaller/pyinstaller.sh --skip-req-install --random-key $PYINSTALLER_ARG

FROM alpine:3.6

LABEL maintainer="Innokenty Lebedev <innlebedev@gmail.com>"

WORKDIR /app

RUN addgroup -S app \
    && adduser -S -G app app \
    && chown app:app .

USER app

EXPOSE 8080 8025

COPY entrypoint.sh .

COPY --from=build /build/dist/app .

ENTRYPOINT ["./entrypoint.sh"]
