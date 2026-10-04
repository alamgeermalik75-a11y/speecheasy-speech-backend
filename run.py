import os
import sys
import socket
import threading
import logging
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("speech_backend_runner")

def start_socket_bridge(listen_port: int, target_port: int):
    """
    Binds to listen_port and forwards TCP traffic to target_port.
    Ensures connectivity whether Railway targets 8000 or 8080.
    """
    def worker():
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("0.0.0.0", listen_port))
            server.listen(128)
            logger.info(f"Port bridge active: 0.0.0.0:{listen_port} -> 127.0.0.1:{target_port}")
            while True:
                client_sock, _ = server.accept()
                def bridge(c_sock):
                    try:
                        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        upstream.connect(("127.0.0.1", target_port))
                        def pipe(src, dst):
                            try:
                                while True:
                                    b = src.recv(8192)
                                    if not b:
                                        break
                                    dst.sendall(b)
                            except Exception:
                                pass
                            finally:
                                try:
                                    src.close()
                                except Exception:
                                    pass
                                try:
                                    dst.close()
                                except Exception:
                                    pass
                        t1 = threading.Thread(target=pipe, args=(c_sock, upstream), daemon=True)
                        t2 = threading.Thread(target=pipe, args=(upstream, c_sock), daemon=True)
                        t1.start()
                        t2.start()
                    except Exception:
                        try:
                            c_sock.close()
                        except Exception:
                            pass
                threading.Thread(target=bridge, args=(client_sock,), daemon=True).start()
        except Exception as e:
            logger.info(f"Port bridge on {listen_port} skipped ({e})")

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    port_env = os.environ.get("PORT")
    if port_env:
        try:
            primary_port = int(port_env)
        except ValueError:
            primary_port = 8000
    else:
        # If on Railway and no PORT is set, default to 8080
        if any(os.environ.get(k) for k in ["RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_STATIC_URL"]):
            primary_port = 8080
        else:
            primary_port = 8000

    # Start fallback bridge for the other common port
    if primary_port == 8080:
        start_socket_bridge(8000, 8080)
    elif primary_port == 8000:
        start_socket_bridge(8080, 8000)

    workers_env = os.environ.get("WEB_CONCURRENCY")
    try:
        workers = int(workers_env) if workers_env else 2
    except ValueError:
        workers = 2

    uvicorn_kwargs = {
        "app": "app.main:app",
        "host": "0.0.0.0",
        "port": primary_port,
        "proxy_headers": True,
        "forwarded_allow_ips": "*",
        "timeout_keep_alive": 75,
        "workers": workers,
    }

    try:
        import uvloop  # type: ignore # noqa
        uvicorn_kwargs["loop"] = "uvloop"
    except ImportError:
        pass

    try:
        import httptools  # type: ignore # noqa
        uvicorn_kwargs["http"] = "httptools"
    except ImportError:
        pass

    logger.info(f"Starting Speech Backend application on 0.0.0.0:{primary_port} (workers={workers}, keepalive=75s)...")
    uvicorn.run(**uvicorn_kwargs)

