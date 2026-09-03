(() => {
  'use strict';

  // Prototype contract: local UI state only. No fetch, WebSocket, storage,
  // service worker, browser permission, or Core call belongs in this file.

  const shell = document.getElementById('shell');
  const markButton = document.getElementById('markButton');
  const voiceButton = document.getElementById('voiceButton');
  const promptInput = document.getElementById('promptInput');
  const composer = document.getElementById('composer');
  const demoButton = document.getElementById('demoButton');
  const stateTitle = document.getElementById('stateTitle');
  const stateSubtitle = document.getElementById('stateSubtitle');
  const presenceText = document.getElementById('presenceText');
  const footerHint = document.getElementById('footerHint');

  const contextStack = document.getElementById('contextStack');
  const responseCard = document.getElementById('responseCard');
  const responseEyebrow = document.getElementById('responseEyebrow');
  const responseCopy = document.getElementById('responseCopy');
  const responseActions = document.getElementById('responseActions');
  const approvalCard = document.getElementById('approvalCard');
  const approvalTitle = document.getElementById('approvalTitle');
  const approvalDetail = document.getElementById('approvalDetail');
  const approveButton = document.getElementById('approveButton');
  const denyButton = document.getElementById('denyButton');

  const presenceButton = document.getElementById('presenceButton');
  const privacyButton = document.getElementById('privacyButton');
  const scrim = document.getElementById('scrim');
  const systemSheet = document.getElementById('systemSheet');
  const closeSheet = document.getElementById('closeSheet');
  const activityValue = document.getElementById('activityValue');
  const haltButton = document.getElementById('haltButton');
  const haltLabel = document.getElementById('haltLabel');
  const haltSub = document.getElementById('haltSub');
  const systemState = document.getElementById('systemState');
  const systemSubstate = document.getElementById('systemSubstate');

  let halted = false;
  let sequence = 0;

  const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  function setState(state, title, subtitle) {
    shell.dataset.state = state;
    stateTitle.textContent = title;
    stateSubtitle.textContent = subtitle;

    const activity = {
      idle: 'Idle',
      listening: 'Listening',
      thinking: 'Thinking',
      answer: 'Responding',
      approval: 'Waiting for approval',
      halted: 'Halted'
    }[state] || state;

    activityValue.textContent = activity;
    presenceText.textContent = state === 'idle' ? 'with you' : activity.toLowerCase();
  }

  function clearCards() {
    contextStack.hidden = true;
    responseCard.hidden = true;
    approvalCard.hidden = true;
    responseActions.replaceChildren();
  }

  function actionChip(label, fn) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'chip-action';
    button.textContent = label;
    button.addEventListener('click', fn);
    return button;
  }

  function showResponse(text, options = {}) {
    contextStack.hidden = false;
    approvalCard.hidden = true;
    responseCard.hidden = false;
    responseEyebrow.textContent = options.eyebrow || 'THEA';
    responseCopy.textContent = text;
    responseActions.replaceChildren();

    if (options.actions) {
      for (const action of options.actions) {
        responseActions.appendChild(actionChip(action.label, action.onClick));
      }
    }

    setState('answer', options.title || 'Here.', options.subtitle || 'Only what matters right now.');
    requestAnimationFrame(() => responseCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
  }

  function showApproval(title = 'Open Barkly on your PC?', detail) {
    if (halted) {
      showResponse('Aletheia is halted. Resume her before approving a computer action.', {
        eyebrow: 'HALTED',
        title: 'Not while halted.',
        subtitle: 'No computer action will run.'
      });
      return;
    }

    contextStack.hidden = false;
    responseCard.hidden = true;
    approvalCard.hidden = false;
    approvalTitle.textContent = title;
    approvalDetail.textContent = detail || 'Aletheia would focus your Windows session and launch one app. No other actions are included.';
    setState('approval', 'Your call.', 'Nothing happens until you approve.');
    requestAnimationFrame(() => approvalCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
  }

  async function runVoiceDemo() {
    if (halted) {
      openSystemSheet();
      return;
    }

    const mine = ++sequence;
    clearCards();
    setState('listening', 'Listening…', 'You can talk naturally.');
    footerHint.textContent = 'Local demo · microphone is not actually active';
    await delay(1150);
    if (mine !== sequence || halted) return;

    setState('thinking', 'On it.', 'Choosing what needs to happen.');
    await delay(1050);
    if (mine !== sequence || halted) return;

    showResponse('You have nothing urgent waiting on you. Barkly had recent repo activity, and your PC is reachable through the private Tailscale path.', {
      title: 'Caught up.',
      subtitle: 'The surface changes with the situation.',
      actions: [
        { label: 'Show Barkly', onClick: () => showApproval() },
        { label: 'Clear', onClick: resetHome }
      ]
    });
    footerHint.textContent = 'Prototype only · no Core connection';
  }

  async function submitPrompt() {
    const text = promptInput.value.trim();
    if (!text) {
      runVoiceDemo();
      return;
    }
    if (halted) {
      openSystemSheet();
      return;
    }

    promptInput.value = '';
    resizeComposer();
    const mine = ++sequence;
    clearCards();
    setState('thinking', 'On it.', text.length > 46 ? `${text.slice(0, 46)}…` : text);
    await delay(600);
    if (mine !== sequence || halted) return;

    const actionIntent = /\b(open|launch|call|send|buy|post|delete|close|start|run)\b/i.test(text);
    if (actionIntent) {
      showApproval('Let Aletheia act on that?', `You asked: “${text}” This prototype treats visible or external effects as a one-time approval instead of silently acting.`);
      return;
    }

    showResponse(`I’d answer “${text}” here, then surface only the controls or context needed for the next step. No dashboard unless you ask for one.`, {
      actions: [
        { label: 'Show action approval', onClick: () => showApproval() },
        { label: 'Clear', onClick: resetHome }
      ]
    });
  }

  function resetHome() {
    ++sequence;
    clearCards();
    if (halted) {
      setState('halted', 'Halted.', 'Tap status to resume Aletheia.');
    } else {
      setState('idle', 'Aletheia', 'Tap the A or just type.');
    }
    document.querySelector('.stage').scrollTo({ top: 0, behavior: 'smooth' });
  }

  function resizeComposer() {
    promptInput.style.height = 'auto';
    promptInput.style.height = `${Math.min(promptInput.scrollHeight, 116)}px`;
    composer.classList.toggle('has-text', Boolean(promptInput.value.trim()));
  }

  function openSystemSheet() {
    scrim.hidden = false;
    systemSheet.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => systemSheet.classList.add('open'));
  }

  function closeSystemSheet() {
    systemSheet.classList.remove('open');
    systemSheet.setAttribute('aria-hidden', 'true');
    setTimeout(() => { scrim.hidden = true; }, 330);
  }

  function toggleHalt() {
    halted = !halted;
    ++sequence;
    clearCards();

    if (halted) {
      setState('halted', 'Halted.', 'No autonomous PC actions.');
      systemState.textContent = 'Halted';
      systemSubstate.textContent = 'Private connection remains available';
      haltLabel.textContent = 'Resume Aletheia';
      haltSub.textContent = 'Re-enables normal operation';
      presenceText.textContent = 'halted';
      footerHint.textContent = 'HALT is visual only in this prototype';
    } else {
      setState('idle', 'Aletheia', 'Tap the A or just type.');
      systemState.textContent = 'Available';
      systemSubstate.textContent = 'Private Tailscale path · local brain';
      haltLabel.textContent = 'HALT Aletheia';
      haltSub.textContent = 'Stops autonomous actions on the PC';
      footerHint.textContent = 'Prototype only · no Core connection';
    }
  }

  markButton.addEventListener('click', runVoiceDemo);
  voiceButton.addEventListener('click', () => composer.classList.contains('has-text') ? submitPrompt() : runVoiceDemo());
  demoButton.addEventListener('click', () => showApproval());

  promptInput.addEventListener('input', resizeComposer);
  promptInput.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submitPrompt();
    }
  });

  presenceButton.addEventListener('click', openSystemSheet);
  privacyButton.addEventListener('click', openSystemSheet);
  closeSheet.addEventListener('click', closeSystemSheet);
  scrim.addEventListener('click', closeSystemSheet);
  haltButton.addEventListener('click', toggleHalt);

  approveButton.addEventListener('click', () => {
    showResponse('Approved once. In the real build, only that exact bound action would be released to Core.', {
      eyebrow: 'APPROVED',
      title: 'Done.',
      subtitle: 'Authority does not carry forward.',
      actions: [{ label: 'Clear', onClick: resetHome }]
    });
  });

  denyButton.addEventListener('click', () => {
    showResponse('Denied. Nothing would be sent to the computer.', {
      eyebrow: 'DENIED',
      title: 'Left alone.',
      subtitle: 'No side effect.',
      actions: [{ label: 'Clear', onClick: resetHome }]
    });
  });

  resizeComposer();
})();