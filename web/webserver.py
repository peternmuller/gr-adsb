#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright 2016-2019 Matt Hostetter.
#
# This is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this software; see the file COPYING.  If not, write to
# the Free Software Foundation, Inc., 51 Franklin Street,
# Boston, MA 02110-1301, USA.
#

from gevent import monkey
monkey.patch_all()

import time
from flask import Flask, request
from flask_socketio import SocketIO
from threading import Thread
import zmq.green as zmq

import pmt
import math
import numpy as np
import json

HTTP_ADDRESS ="127.0.0.1"
HTTP_PORT = 5000

ZMQ_ADDRESS = "127.0.0.1"
ZMQ_PORT = 5001

app = Flask(__name__, static_url_path="")
app.config["SECRET_KEY"] = "secret!"

print(f"[webserver] Starting Flask app on http://{HTTP_ADDRESS}:{HTTP_PORT}")
socketio = SocketIO(
    app,
    cors_allowed_origins=[f"http://{HTTP_ADDRESS}:{HTTP_PORT}", "http://localhost:5000", "*"],
    async_mode="gevent",
)
print("[webserver] SocketIO initialized with CORS for:", [f"http://{HTTP_ADDRESS}:{HTTP_PORT}", "http://localhost:5000", "*"])


def zmq_thread():
    print(f"[webserver] ZMQ thread starting. Connecting to tcp://{ZMQ_ADDRESS}:{ZMQ_PORT}")
    # Establish ZMQ context and socket
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.setsockopt(zmq.SUBSCRIBE, b"")
    socket.connect("tcp://{:s}:{:d}".format(ZMQ_ADDRESS, ZMQ_PORT))

    while True:
        # Receive decoded ADS-B message from the decoder over ZMQ
        pdu_bin = socket.recv()
        print("[webserver] Received raw PDU bytes from ZMQ, length:", len(pdu_bin))
        try:
            pdu = pmt.deserialize_str(pdu_bin)
            plane = pmt.to_python(pmt.car(pdu))
            print("[webserver] Decoded plane dict from ZMQ:", plane)
        except Exception as e:
            print("[webserver] ERROR decoding PDU from ZMQ:", e)
            continue

        def sanitize_for_json(obj):
            """Recursively convert values to JSON-safe Python types.

            - Replace NaN/inf with None
            - Convert numpy scalars/arrays to native Python types
            - Decode bytes to str where possible
            """
            # dict
            if isinstance(obj, dict):
                return {k: sanitize_for_json(v) for k, v in obj.items()}
            # list/tuple
            if isinstance(obj, (list, tuple)):
                return [sanitize_for_json(v) for v in obj]
            # numpy array -> list
            if isinstance(obj, np.ndarray):
                return sanitize_for_json(obj.tolist())
            # numpy scalar
            if isinstance(obj, (np.floating, np.integer, np.bool_)):
                try:
                    py = obj.item()
                except Exception:
                    py = obj
                return sanitize_for_json(py)
            # floats (including Python float)
            if isinstance(obj, float):
                if not math.isfinite(obj):
                    return None
                return float(obj)
            # ints/bools/str/None
            if isinstance(obj, (int, bool, str)) or obj is None:
                return obj
            # bytes -> try decode
            if isinstance(obj, (bytes, bytearray)):
                try:
                    return obj.decode()
                except Exception:
                    return None
            # fallback: try to coerce numpy.generic or other items
            try:
                if hasattr(obj, 'item'):
                    return sanitize_for_json(obj.item())
            except Exception:
                pass
            # unknown type: convert to string as a last resort
            try:
                return str(obj)
            except Exception:
                return None

        def finalize_plane(p):
            # Ensure well-typed fields for the client
            if not isinstance(p, dict):
                return p
            out = p.copy()
            if out.get('callsign') is None:
                out['callsign'] = ''
            for k in ('latitude', 'longitude'):
                v = out.get(k)
                if v is None:
                    out[k] = None
                else:
                    try:
                        out[k] = float(v)
                    except Exception:
                        out[k] = None
            for k in ('speed', 'heading', 'altitude', 'vertical_rate'):
                v = out.get(k)
                if v is None:
                    out[k] = None
                else:
                    try:
                        if k == 'altitude':
                            out[k] = int(float(v))
                        else:
                            out[k] = float(v)
                    except Exception:
                        out[k] = None
            return out

        try:
            safe_plane = sanitize_for_json(plane)
            safe_plane = finalize_plane(safe_plane)
            try:
                js = json.dumps(safe_plane, allow_nan=False)
            except TypeError as e:
                print('[webserver] JSON serialization TypeError for plane:', e, 'plane repr:', repr(safe_plane))
                safe_plane = {k: (v if v is not None else None) for k, v in safe_plane.items()}
                js = json.dumps(safe_plane, allow_nan=False)
            except ValueError as e:
                print('[webserver] JSON serialization ValueError (likely NaN/inf) for plane:', e, 'plane repr:', repr(safe_plane))
                def replace_nan(o):
                    if isinstance(o, dict):
                        return {k: replace_nan(v) for k, v in o.items()}
                    if isinstance(o, list):
                        return [replace_nan(v) for v in o]
                    try:
                        if isinstance(o, float) and not math.isfinite(o):
                            return None
                    except Exception:
                        pass
                    return o
                safe_plane = replace_nan(safe_plane)
                js = json.dumps(safe_plane, allow_nan=False)

            print('[webserver] Emitting JSON size:', len(js))
            socketio.emit("updatePlane", safe_plane)
            print("[webserver] Emitted updatePlane via SocketIO for ICAO:", safe_plane.get("icao"))
        except Exception as e:
            print("[webserver] ERROR emitting updatePlane via SocketIO:", e)


@app.route("/")
def index():
    print("[webserver] HTTP GET / - serving index.html")
    return app.send_static_file("index.html")


@socketio.on("connect")
def connect():
    print("[webserver] Client connected:", request.sid)


@socketio.on("disconnect")
def disconnect():
    print("[webserver] Client disconnected:", request.sid)


if __name__ == "__main__":
    print("[webserver] __main__ starting zmq_thread...")
    thread = Thread(target=zmq_thread)
    thread.daemon = True
    thread.start()
    print("[webserver] zmq_thread started. Launching SocketIO web server...")

    socketio.run(app, host=HTTP_ADDRESS, port=HTTP_PORT, debug=True, use_reloader=False)
