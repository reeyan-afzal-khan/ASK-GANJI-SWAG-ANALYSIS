yt-dlp \
  --extract-audio \
  --audio-format mp3 \
  --audio-quality 0 \
  --sleep-interval 5 \
  --max-sleep-interval 15 \
  -o "episode_%(playlist_index)03d.%(ext)s" \
  "https://www.youtube.com/playlist?list=PLinUrn8TVRE-hm3-CsyoQaySKYbxLtG6B"
  
  