"""Start Gårdopgaver.

    python run.py              # produktion (waitress) på port 8000, tilgængelig på det lokale netværk
    python run.py --port 8080  # anden port
    python run.py --dev        # udviklingsserver med automatisk genindlæsning
"""

import argparse
import logging
import os
import socket

# Kører vi som Home Assistant-app (options.json findes altid dér), så slå Home Assistant-tilstand
# til, selv hvis miljøvariablerne mangler – ellers ville data blive gemt uden for /data.
if os.path.exists("/data/options.json"):
    os.environ.setdefault("GAARD_HA", "1")
    os.environ.setdefault("GAARD_DATA_DIR", "/data")

from gaardopgaver import create_app  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Start Gårdopgaver")
    parser.add_argument("--host", default="0.0.0.0", help="Adresse at lytte på (standard: alle netkort)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dev", action="store_true", help="Udviklingstilstand")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = create_app()
    print(f"Gårdopgaver kører på http://localhost:{args.port}")
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if not ip.startswith("127."):
            print(f"Fra andre enheder på netværket: http://{ip}:{args.port}")
    except OSError:
        pass
    print(f"Data gemmes i: {app.config['DATABASE']}")

    if args.dev:
        app.run(host=args.host, port=args.port, debug=True)
    else:
        from waitress import serve

        serve(app, host=args.host, port=args.port, threads=8)


if __name__ == "__main__":
    main()
