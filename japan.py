import requests
import re

UPSTREAM_URL = "https://web.utako.moe/jp.m3u"
OUTPUT_FILE = "JapanTV.m3u8"
FORCED_GROUP_NAME = "JapanTV"
TVG_HEADER = '#EXTM3U url-tvg="https://epg.freejptv.com/jp.xml,https://animenosekai.github.io/japanterebi-xmltv/guide.xml" tvg-shift=0'

group_regex = re.compile(r'group-title=".*?"')

def get_existing_urls(file_path):
    urls = set()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if line.startswith("#EXTINF") and i + 1 < len(lines):
                urls.add(lines[i + 1].strip())
        return urls
    except FileNotFoundError:
        return set()

def clean_and_force_group(m3u_content, existing_urls):
    lines = m3u_content.strip().splitlines()
    output_lines = []
    skip_next = False

    for i, line in enumerate(lines):
        if skip_next:
            skip_next = False
            continue

        if line.startswith("#EXTINF"):
            if 'group-title="Information"' in line:
                skip_next = True
                continue

            if i + 1 < len(lines):
                url_line = lines[i + 1].strip()
                if url_line not in existing_urls:
                    if 'group-title="' in line:
                        line = group_regex.sub(f'group-title="{FORCED_GROUP_NAME}"', line)
                    else:
                        line = line.replace('#EXTINF:', f'#EXTINF group-title="{FORCED_GROUP_NAME}":')

                    output_lines.append(line)
                    output_lines.append(url_line)
                skip_next = True
    return output_lines

def main():
    response = requests.get(UPSTREAM_URL)
    if response.status_code != 200:
        print(f"❌ Failed to download: HTTP {response.status_code}")
        return

    existing_urls = get_existing_urls(OUTPUT_FILE)
    modified_lines = clean_and_force_group(response.text, existing_urls)

    if not existing_urls:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(TVG_HEADER + "\n")
            f.write("\n".join(modified_lines) + "\n")
        print(f"✅ Created {OUTPUT_FILE} with new entries")
    elif modified_lines:
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(modified_lines) + "\n")
        print(f"✅ Appended {len(modified_lines)//2} new entries to {OUTPUT_FILE}")
    else:
        print("ℹ No new entries, playlist unchanged")

if __name__ == "__main__":
    main()
