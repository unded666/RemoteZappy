(async () => {
  const startButton = document.getElementById('start');
  const localVideo = document.getElementById('local');
  const remoteVideo = document.getElementById('remote');

  let pc = null;
  let inputChannel = null;

  startButton.onclick = async () => {
    startButton.disabled = true;

    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    localVideo.srcObject = stream;

    pc = new RTCPeerConnection();

    // create a reliable datachannel for input events
    inputChannel = pc.createDataChannel('input');
    inputChannel.onopen = () => {
      console.log('input datachannel open');
      // Send a small hello so the server knows it's active (optional)
      try { inputChannel.send(JSON.stringify({type:'hello'})); } catch(e){}
    };
    inputChannel.onclose = () => { console.log('input datachannel closed'); };
    inputChannel.onerror = (e) => { console.log('input datachannel error', e); };

    // send keyboard events to the server when the channel is open
    const sendKeyEvent = (ev) => {
      if (!inputChannel || inputChannel.readyState !== 'open') return;
      // normalize key info
      const msg = {
        type: 'key',
        key: ev.key,        // e.g., 'ArrowUp', 'a', 'Enter', ' '
        code: ev.code,     // e.g., 'ArrowUp', 'KeyA'
        altKey: ev.altKey,
        ctrlKey: ev.ctrlKey,
        shiftKey: ev.shiftKey,
        metaKey: ev.metaKey,
        timestamp: Date.now(),
        down: ev.type === 'keydown'
      };
      try {
        inputChannel.send(JSON.stringify(msg));
      } catch (e) {
        console.warn('failed to send key event', e);
      }
    };

    // Attach listeners (keydown only to reduce duplication); also send keyup
    window.addEventListener('keydown', sendKeyEvent);
    window.addEventListener('keyup', sendKeyEvent);

    // show incoming tracks
    pc.ontrack = (event) => {
      console.log('remote track', event);
      remoteVideo.srcObject = event.streams[0];
    };

    // send local tracks
    for (const track of stream.getTracks()) {
      pc.addTrack(track, stream);
    }

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    // send offer to server
    const resp = await fetch('/offer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sdp: pc.localDescription.sdp, type: pc.localDescription.type })
    });

    const answer = await resp.json();
    await pc.setRemoteDescription(answer);

    console.log('Connection established');
  };
})();
