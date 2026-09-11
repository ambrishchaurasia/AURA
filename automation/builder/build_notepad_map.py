"""
Script to build the initial Notepad App Map using the crawler.
"""

import sys
import os
import time
import subprocess

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from automation.builder.crawler import UIACrawler, save_app_map
from automation.core import window_manager

def main():
    print("Starting Notepad...")
    # Kill existing to be safe
    subprocess.run(["taskkill", "/IM", "notepad.exe", "/F"], capture_output=True)
    time.sleep(1)
    
    # Launch new instance
    subprocess.Popen("notepad.exe")
    time.sleep(3)  # Wait for full UI init
    
    # Find window
    window = window_manager.find_window_simple("Notepad")
    if not window:
        print("Error: Could not find Notepad window.")
        return
        
    print(f"Found window: {window.window_text()}")
    
    # Crawl
    crawler = UIACrawler()
    app_map = crawler.crawl(window, max_depth=6)
    
    # Save
    out_path = os.path.join(os.path.dirname(__file__), "../../app_maps/notepad.json")
    save_app_map(app_map, out_path)
    
    print("Done. You may need to manually refine the generated app map.")

if __name__ == "__main__":
    main()
