import faulthandler, threading, time, sys
faulthandler.enable()
def dump_later():
    time.sleep(3)
    print("DUMPING THREADS", file=sys.stderr)
    faulthandler.dump_traceback(sys.stderr)
threading.Thread(target=dump_later, daemon=True).start()
from automation.mcp.server import mcp
mcp.run()
