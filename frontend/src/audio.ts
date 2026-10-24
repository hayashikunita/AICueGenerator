// Keep library preview and result playback from speaking over one another.
export function pauseOtherAudio(active: HTMLAudioElement) {
  document.querySelectorAll("audio").forEach((audio) => {
    if (audio !== active) audio.pause();
  });
}
