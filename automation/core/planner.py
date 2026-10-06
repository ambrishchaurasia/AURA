"""
AURA Rule-Based Sequential Planner (Fallback when LLM is offline)

Parses natural language prompts and translates them into an ordered sequence
of actionable steps for Notepad and Explorer agents, preserving context across steps.
"""

import re
from typing import List, Dict

class SimplePlanner:
    def plan(self, prompt: str) -> List[Dict]:
        """
        Parses multi-app prompts and translates them into an ordered sequence
        of actions based on clause sequence and intent keywords.
        """
        prompt_trim = prompt.strip()
        if not prompt_trim:
            return []

        # Split on sequential conjunctions and multi-verb "and"
        split_pattern = r'\b(?:and\s+then|then|after\s+that|next|also)\b|(?<=\w)\s+and\s+(?=(?:open|write|type|edit|save|go|navigate|create))\b|[,;]'
        raw_segments = re.split(split_pattern, prompt_trim, flags=re.IGNORECASE)
        segments = [s.strip() for s in raw_segments if s.strip()]

        # Secondary split for un-punctuated multi-action phrases e.g. "go to documents open hello.txt"
        sub_segments = []
        for seg in segments:
            parts = re.split(r'\s+(?=(?:open|go\s+to|navigate|edit|write|type|save|create)\b)', seg, flags=re.IGNORECASE)
            for p in parts:
                if p.strip():
                    sub_segments.append(p.strip())

        actions = []
        last_filename = "hello.txt"
        last_folder = ""
        is_file_saved = False

        for seg in sub_segments:
            seg_lower = seg.lower()

            # 1. Extract potential filename if present in this clause
            fn_named_match = re.search(
                r"(?:text\s+)?(?:document|file|image|picture|photo|video)\s+(?:named|called)\s+['\"]?([a-zA-Z0-9_\-\.\s]+?)['\"]?(?:\s+in|\s+and|\s+with|$)",
                seg,
                re.IGNORECASE
            )
            if fn_named_match:
                last_filename = fn_named_match.group(1).strip()
            else:
                open_item_match = re.search(
                    r"\bopen\s+(?:the\s+)?(?:file|document|image|picture|photo|video|text\s+document)?\s*['\"]?([a-zA-Z0-9_\-\.\s]+?)['\"]?(?:\s+in|\s+and|\s+with|$)",
                    seg,
                    re.IGNORECASE
                )
                if open_item_match and open_item_match.group(1).strip().lower() not in ("file explorer", "explorer", "notepad", "it", "file", "document", "the file", "the"):
                    last_filename = open_item_match.group(1).strip()
                else:
                    fn_match = re.search(r"\b([a-zA-Z0-9_\-]+\.[a-zA-Z0-9]{2,4})\b", seg)
                    if fn_match:
                        last_filename = fn_match.group(1).strip()
                    else:
                        fn_save = re.search(
                            r"save(?:\s+it)?\s+(?:as\s+)?['\"]?([a-zA-Z0-9_\-\.]+)",
                            seg,
                            re.IGNORECASE
                        )
                        if fn_save:
                            cand = fn_save.group(1).strip()
                            if cand.lower() not in ("it", "the", "file", "text", "document", "in", "to", "on", "as"):
                                last_filename = cand

            # 2. Extract potential folder if present
            go_to_match = re.search(r"(?:go\s+to|navigate\s+(?:to\s+)?)\s+(.+?)(?:\s+and\s+open|\s+and|\s+open\s+|$)", seg, re.IGNORECASE)
            if go_to_match:
                cand_folder = go_to_match.group(1).strip()
                if cand_folder and not any(w in cand_folder.lower() for w in ["file explorer", "notepad"]) and not re.search(r"\.[a-zA-Z0-9]{2,4}$", cand_folder):
                    last_folder = cand_folder

            if not last_folder:
                for folder_kw in ["downloads", "documents", "desktop", "pictures", "videos", "music"]:
                    if folder_kw in seg_lower:
                        last_folder = folder_kw.capitalize()
                        break

            # 3. Check actions in chronological order within segment

            # Open Notepad
            if "open notepad" in seg_lower or "launch notepad" in seg_lower:
                actions.append({"agent": "notepad", "action": "open", "params": {}})

            # Open or Navigate File Explorer (e.g. "open file explorer", "go to downloads")
            elif re.search(r"\b(?:open|launch)\s+(?:file\s+explorer|explorer)\b", seg_lower) or (("go to" in seg_lower or "navigate" in seg_lower) and not "open " in seg_lower):
                if last_folder:
                    actions.append({"agent": "explorer", "action": "navigate", "params": {"path": last_folder}})
                else:
                    actions.append({"agent": "explorer", "action": "open", "params": {}})

            # Open Item / File (e.g. "open hello.txt", "open it", "open file hello.txt")
            elif bool(re.search(r"\bopen\s+(?:it|file\b(?!\s+explorer)|document|text\s+document|['\"]?[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]{2,4}['\"]?)\b", seg_lower)) or ("open " in seg_lower and last_filename.lower() in seg_lower and not "notepad" in seg_lower and not "file explorer" in seg_lower):
                actions.append({"agent": "explorer", "action": "open_item", "params": {"filename": last_filename}})
                is_file_saved = True

            # General Go to / Navigate fallback
            elif ("go to" in seg_lower or "navigate" in seg_lower) and last_folder:
                actions.append({"agent": "explorer", "action": "navigate", "params": {"path": last_folder}})

            # Type / Write / Edit
            if any(w in seg_lower for w in ["type", "write", "edit", "add text", "append"]):
                match = re.search(
                    r"(?:type|write|edit|add\s+text|append)\s+(?:['\"](?P<quoted>[^'\"]+)['\"]|(?P<unquoted>.+?))(?:\s+(?:and|like|save)|[,.;]|$)",
                    seg,
                    re.IGNORECASE,
                )
                text_to_type = (match.group("quoted") or match.group("unquoted") or "Edited content from AURA.").strip() if match else "Edited content from AURA."
                if text_to_type.lower() in ("it", "the file", "file", last_filename.lower(), "like that", "it like that", "it and save", "it and save it"):
                    text_to_type = "\nEdited text added by AURA."
                actions.append({"agent": "notepad", "action": "type", "params": {"text": text_to_type}})

            # Save As vs Save
            if "save as" in seg_lower or ("save" in seg_lower and not is_file_saved):
                path = last_folder if any(k in seg_lower for k in ["in downloads", "to downloads", "in documents", "on desktop"]) else ""
                actions.append({"agent": "notepad", "action": "save_as", "params": {"filename": last_filename, "path": path}})
                is_file_saved = True
            elif "save" in seg_lower and is_file_saved and not any(w in seg_lower for w in ["save as"]):
                actions.append({"agent": "notepad", "action": "save", "params": {}})

        # Fallback if no specific clause actions were parsed
        if not actions:
            has_notepad = "notepad" in prompt_trim.lower() or any(w in prompt_trim.lower() for w in ["type", "write", "save as"])
            has_explorer = any(w in prompt_trim.lower() for w in ["explorer", "folder", "downloads", "directory"])
            if has_notepad:
                actions.append({"agent": "notepad", "action": "open", "params": {}})
            if has_explorer:
                actions.append({"agent": "explorer", "action": "open", "params": {}})

        return actions


