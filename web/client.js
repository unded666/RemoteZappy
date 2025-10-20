(async () => {
  const startButton = document.getElementById('start');
  const localVideo = document.getElementById('local');
  const remoteVideo = document.getElementById('remote');
  const webrtcStatusEl = document.getElementById('webrtc-status');
  const dcStatusEl = document.getElementById('dc-status');
  const lastCmdEl = document.getElementById('last-cmd');

  let pc = null;
  let inputChannel = null;

  const setStatus = (el, text, ok) => {
    if (!el) return;
    el.textContent = text;
    el.className = ok ? 'green' : 'red';
  };

  startButton.onclick = async () => {
    startButton.disabled = true;

    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    localVideo.srcObject = stream;

    pc = new RTCPeerConnection();
    setStatus(webrtcStatusEl, 'connecting', false);

    // track connection state
    pc.onconnectionstatechange = () => {
      try {
        const s = pc.connectionState || pc.iceConnectionState || 'unknown';
        setStatus(webrtcStatusEl, s, s === 'connected');
      } catch (e) {
        setStatus(webrtcStatusEl, 'error', false);
      }
    };

    // create a reliable datachannel for input events
    inputChannel = pc.createDataChannel('input');
    inputChannel.onopen = () => {
      console.log('input datachannel open');
      setStatus(dcStatusEl, 'open', true);
      // Send a small hello so the server knows it's active (optional)
      try { inputChannel.send(JSON.stringify({type:'hello'})); } catch(e){}
    };
    inputChannel.onclose = () => { console.log('input datachannel closed'); setStatus(dcStatusEl, 'closed', false); };
    inputChannel.onerror = (e) => { console.log('input datachannel error', e); setStatus(dcStatusEl, 'error', false); };

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

    // Hook up command buttons to send simple command messages via the datachannel
    const sendCommand = (command) => {
      if (!inputChannel || inputChannel.readyState !== 'open') {
        console.warn('input channel not open, cannot send command', command);
        return;
      }
      try {
        inputChannel.send(JSON.stringify({ type: 'command', command }));
        // UI feedback: update last command
        if (lastCmdEl) {
          lastCmdEl.textContent = command;
          lastCmdEl.className = 'green';
          setTimeout(() => { if (lastCmdEl) lastCmdEl.className = ''; }, 400);
        }
      } catch (e) {
        console.warn('failed to send command', e);
      }
    };

    const cmds = ['fire','ice','projectile','shield','magnify'];
    for (const c of cmds) {
      const el = document.getElementById('cmd-' + c);
      if (el) {
        el.addEventListener('click', () => {
          sendCommand(c);
          // small UI feedback
          el.style.opacity = '0.6';
          setTimeout(() => { el.style.opacity = '1'; }, 120);
        });
      }
    }
  };
})();
