'use strict';

(() => {
  function createOffice(canvas, onUpdate, schedule, reduced) {
    if (!canvas) return null;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    canvas.width = 540;
    canvas.height = 308;
    canvas.style.imageRendering = 'pixelated';

    const rooms = {
      arastirma: { label: 'Araştırma', x: 11, y: 12, w: 310, h: 143, door: 166, roomY: 117, color: '#83a6a3' },
      belge: { label: 'Belgeler', x: 334, y: 32, w: 194, h: 123, door: 418, roomY: 123, color: '#b9a286' },
      kontrol: { label: 'Kontrol', x: 43, y: 178, w: 221, h: 118, door: 169, roomY: 214, color: '#9b9ab7' },
      salon: { label: 'Ekip odası', x: 281, y: 178, w: 247, h: 105, door: 398, roomY: 219, color: '#9aab9b' },
    };
    const ids = Object.keys(rooms);
    const people = [
      { name: 'Ada', role: 'Araştırmacı', color: '#79a9a6', hair: '#2d2630', skin: '#d5a588', room: 'arastirma' },
      { name: 'Deniz', role: 'Belge uzmanı', color: '#c4957b', hair: '#4b3437', skin: '#e0bda4', room: 'belge' },
      { name: 'Elif', role: 'Doğrulama uzmanı', color: '#a396b6', hair: '#322a37', skin: '#b67d64', room: 'kontrol' },
      { name: 'Mert', role: 'Koordinatör', color: '#809bb9', hair: '#563936', skin: '#d8a685', room: 'salon' },
    ];
    const paint = canvas.ownerDocument.createElement('canvas');
    paint.width = canvas.width;
    paint.height = canvas.height;
    const artist = paint.getContext('2d');
    if (!artist) return null;
    const fill = (surface, x, y, w, h, color) => {
      surface.fillStyle = color;
      surface.fillRect(x, y, w, h);
    };
    const box = (x, y, w, h, color) => fill(artist, x, y, w, h, color);

    function surface(x, y, w, h, top, edge) {
      box(x + 3, y + 5, w, h, '#141922');
      box(x, y, w, h, '#2d2b38');
      box(x, y, w, h - 4, top);
      box(x, y, w, 2, edge);
      box(x + 2, y + h - 4, w - 4, 1, edge);
    }
    function floor(x, y, w, h, seed = 0) {
      box(x, y, w, h, '#252935');
      for (let row = 0; row * 8 < h; row++) {
        const top = y + row * 8;
        for (let col = -1; col * 15 < w; col++) {
          const from = Math.max(x, x + col * 15 + (row % 2) * 7);
          const to = Math.min(x + w, x + (col + 1) * 15 - 1 + (row % 2) * 7);
          if (from < to) {
            const slate = ['#333945', '#343a46', '#363c48', '#323743'];
            box(from, top, to - from, Math.min(7, y + h - top), slate[(row * 3 + col + seed + 4) % 4]);
          }
        }
      }
    }
    function frame(room, index) {
      const { x, y, w, h } = room;
      box(x - 3, y - 3, w + 6, h + 6, '#121620');
      box(x, y, w, h, '#4f5666');
      box(x + 2, y + 2, w - 4, 3, '#697180');
      box(x + 3, y + 5, w - 6, 6, '#383c4b');
      floor(x + 6, y + 11, w - 12, h - 16, index);
      box(x + 5, y + h - 5, w - 10, 2, '#3f4553');
      box(x + 6, y + 8, w - 12, 2, '#74707a');
      for (let vx = x + 10; vx < x + w - 8; vx += 12) box(vx, y + 4, 1, 5, '#47505d');
    }
    function doorway(x, y, w, h) {
      floor(x, y, w, h, 2);
      box(x - 2, y, 3, h, '#9e7562');
      box(x + w - 1, y, 3, h, '#9e7562');
      box(x - 2, y, 2, 4, '#d2ac87');
      box(x + w, y, 2, 4, '#d2ac87');
    }
    function wallOpening(x, y, w, h) {
      floor(x, y, w, h, 1);
      box(x, y - 2, w, 3, '#9c7967');
      box(x, y + h - 1, w, 3, '#9c7967');
    }
    function plant(x, y) {
      box(x, y + 9, 14, 8, '#212630');
      surface(x + 2, y + 6, 10, 10, '#8c645a', '#b58b71');
      box(x + 1, y + 1, 12, 8, '#4d7160');
      box(x + 4, y - 4, 5, 11, '#81a178');
      box(x + 9, y - 2, 4, 6, '#698b72');
      box(x - 1, y, 5, 5, '#5d866d');
    }
    function screen(x, y, color) {
      box(x + 9, y + 12, 4, 4, '#282533');
      box(x, y, 22, 13, '#1c202d');
      box(x + 1, y + 1, 20, 10, '#647286');
      box(x + 2, y + 2, 18, 8, '#354d5d');
      box(x + 4, y + 4, 4, 2, color);
      box(x + 10, y + 4, 7, 1, '#a5c9cc');
      box(x + 4, y + 7, 11, 1, '#94adb3');
    }
    function desk(x, y, width, color, dual = false) {
      surface(x, y, width, 25, '#665753', '#967a6d');
      box(x + 4, y + 16, width - 8, 3, '#715e58');
      screen(x + 7, y + 2, color);
      if (dual) screen(x + 34, y + 1, '#a7b6bd');
      else {
        box(x + width - 21, y + 5, 12, 10, '#bca98e');
        box(x + width - 18, y + 8, 6, 1, '#8f826e');
        box(x + width - 18, y + 11, 5, 1, '#8f826e');
      }
      box(x + 8, y + 18, 19, 3, '#312e3b');
      for (let i = 0; i < 5; i++) box(x + 10 + i * 3, y + 18, 2, 1, '#a4a6a7');
      const seat = x + Math.floor(width / 2) - 8;
      surface(seat, y + 28, 16, 13, '#3d4a60', '#6e7b91');
      box(seat + 3, y + 30, 10, 5, '#616d83');
    }
    function bookcase(x, y, slots, tint = '#b6957a') {
      const w = slots * 6 + 8;
      surface(x, y, w, 22, '#66544e', '#aa8471');
      box(x + 3, y + 5, w - 6, 12, '#371f2a');
      for (let i = 0; i < slots; i++) {
        const b = [tint, '#6b8092', '#a37e77', '#a0a17f', '#817d9a'][i % 5];
        const height = 6 + i % 5;
        box(x + 4 + i * 6, y + 16 - height, 4, height, b);
        if (i % 2) box(x + 5 + i * 6, y + 14, 2, 1, '#c4b1a4');
      }
      box(x + 2, y + 17, w - 4, 2, '#8f705f');
    }
    function consoleCabinet(x, y, tint) {
      surface(x, y, 26, 25, '#4a4c5e', '#7a7182');
      box(x + 4, y + 5, 17, 8, '#233149');
      box(x + 6, y + 7, 4, 2, tint);
      box(x + 12, y + 7, 6, 1, '#6b789d');
      box(x + 6, y + 11, 11, 1, '#587891');
      box(x + 4, y + 16, 17, 2, '#767184');
    }
    function couch(x, y, width, color) {
      surface(x, y, width, 26, color, '#8b7c86');
      box(x + 5, y + 6, width - 10, 12, '#717181');
      box(x + Math.floor(width / 2), y + 5, 2, 14, '#555566');
      box(x + 6, y + 5, 10, 7, '#a17e79');
      box(x + width - 16, y + 5, 10, 7, '#929f9a');
    }
    function rug(x, y, w, h) {
      box(x, y, w, h, '#434351');
      for (let i = 0; i < 3; i++) {
        box(x + 2 + 3 * i, y + 2 + i * 3, w - 4 - i * 6, 1, '#61582f');
        box(x + 2 + 3 * i, y + h - 3 - i * 3, w - 4 - i * 6, 1, '#61582f');
      }
    }
    function label(room) {
      artist.font = 'bold 8px monospace';
      artist.fillStyle = room.color;
      artist.fillText(room.label.toLocaleUpperCase('tr-TR'), room.x + 13, room.y + 23);
    }

    function scenery() {
      box(0, 0, 540, 308, '#171b26');
      for (let y = 1; y < 308; y += 10) {
        for (let x = 1; x < 540; x += 10) {
          if ((x * 2 + y * 5) % 7 < 2) box(x, y, 1, 1, '#2b3040');
        }
      }

      for (const [index, room] of Object.values(rooms).entries()) {
        frame(room, index);
        label(room);
      }

      floor(21, 155, 506, 23, 0);
      box(21, 155, 506, 2, '#575663');
      box(21, 176, 506, 2, '#575663');
      doorway(rooms.arastirma.door - 14, 147, 28, 12);
      doorway(rooms.belge.door - 14, 147, 28, 12);
      doorway(rooms.kontrol.door - 14, 174, 28, 16);
      doorway(rooms.salon.door - 14, 174, 28, 16);
      wallOpening(314, 86, 28, 20);
      wallOpening(258, 232, 29, 19);

      bookcase(24, 40, 10);
      consoleCabinet(111, 39, '#90a8ad');
      consoleCabinet(144, 38, '#8faca4');
      bookcase(228, 39, 10, '#92a396');
      plant(298, 44);
      desk(31, 74, 68, '#91b1a7', true);
      desk(125, 72, 72, '#94b8b2', true);
      desk(219, 76, 71, '#9db4ba', true);
      plant(25, 129);
      box(16, 118, 7, 5, '#676875');

      bookcase(350, 60, 10, '#b59b83');
      bookcase(432, 60, 12, '#aaa795');
      bookcase(486, 95, 4, '#b1a386');
      desk(350, 105, 50, '#a8aea2');
      surface(447, 99, 25, 34, '#615b60', '#75727a');
      box(452, 105, 15, 9, '#beab94');
      box(455, 108, 9, 1, '#887c74');
      plant(502, 130);

      bookcase(54, 208, 6, '#9795aa');
      desk(57, 245, 71, '#a0b5bb', true);
      desk(184, 240, 65, '#a8a3ba', true);
      consoleCabinet(213, 202, '#b89aab');
      plant(137, 266);

      rug(305, 220, 142, 50);
      couch(309, 225, 68, '#5b596b');
      surface(378, 243, 36, 18, '#6f5d55', '#8e7665');
      box(385, 247, 11, 5, '#b0a48d');
      bookcase(450, 207, 9, '#aea18a');
      couch(453, 238, 55, '#666270');
      plant(511, 261);
    }

    scenery();
    const hall = 166;
    let selected = 0;
    let paused = false;
    let destroyed = false;
    const isPaused = () => paused || reduced.matches;
    let nextMove = 1450;
    let cycle = 0;
    const workplace = (id, index) => {
      const offsets = id === 'belge' ? [-10, 5, 16, -2] : [-10, 7, 16, -21];
      return [rooms[id].door + offsets[index], rooms[id].roomY];
    };
    people.forEach((person, index) => {
      [person.x, person.y] = workplace(person.room, index);
      person.destination = null;
      person.path = [];
      person.phase = 0;
    });

    function notify() {
      if (destroyed) return;
      onUpdate?.({
        people: people.map(person => ({
          name: person.name,
          role: person.role,
          color: person.color,
          room: rooms[person.room].label,
          destination: person.destination ? rooms[person.destination].label : null,
        })),
        selected,
        paused: isPaused(),
      });
    }

    function draw() {
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(paint, 0, 0);
      const ordered = [...people].sort((a, b) => a.y - b.y);
      for (const person of ordered) {
        const x = Math.round(person.x);
        const y = Math.round(person.y);
        const step = person.path.length ? Math.floor(person.phase / 4) % 2 : 0;
        if (people[selected] === person) {
          fill(ctx, x - 7, y + 4, 14, 1, '#cbdace');
          fill(ctx, x - 8, y, 1, 4, '#cbdace');
          fill(ctx, x + 7, y, 1, 4, '#cbdace');
        }
        fill(ctx, x - 5, y + 1, 10, 3, '#222431');
        fill(ctx, x - 3, y + step, 2, 4, '#2b2c3b');
        fill(ctx, x + 1, y + 1 - step, 2, 4, '#2b2c3b');
        fill(ctx, x - 4, y - 7, 8, 8, person.color);
        fill(ctx, x - 5, y - 5, 2, 5, person.color);
        fill(ctx, x + 3, y - 5 + step, 2, 5, person.color);
        fill(ctx, x - 4, y - 14, 8, 8, person.hair);
        fill(ctx, x - 3, y - 11, 6, 5, person.skin);
        fill(ctx, x - 2, y - 9, 1, 1, '#533c3c');
        fill(ctx, x + 1, y - 9, 1, 1, '#533c3c');
        fill(ctx, x - 1, y - 7, 2, 2, person.skin);
      }
      const active = people[selected];
      const label = active.destination ? 'Yolda…' : active.room === 'arastirma' ? 'Araştırıyor…' : rooms[active.room].label;
      ctx.font = '8px monospace';
      const bubbleWidth = Math.ceil(ctx.measureText(label).width) + 10;
      const bx = Math.round(active.x - bubbleWidth / 2);
      const by = Math.round(active.y - 32);
      fill(ctx, bx, by + 1, bubbleWidth, 12, '#1b2029');
      fill(ctx, bx + 1, by, bubbleWidth - 2, 11, '#dce2e2');
      fill(ctx, Math.round(active.x - 1), by + 11, 3, 2, '#dce2e2');
      ctx.fillStyle = '#202936';
      ctx.fillText(label, bx + 5, by + 8);
    }

    function movePerson(index, id) {
      const person = people[index];
      if (destroyed || !Object.hasOwn(rooms, id) || person.destination === id || (!person.destination && person.room === id)) return false;
      if (reduced.matches) {
        [person.x, person.y] = workplace(id, index);
        person.room = id;
        person.destination = null;
        person.path = [];
        draw();
        notify();
        return true;
      }
      const inHall = person.y >= 155 && person.y < 178;
      const current = person.y < 155 ? (person.x < 326 ? 'arastirma' : 'belge')
        : (person.x < 274 ? 'kontrol' : 'salon');
      const entry = rooms[id].door;
      const [x, y] = workplace(id, index);
      person.path = inHall ? [[person.x, hall]] : [[rooms[current].door, person.y], [rooms[current].door, hall]];
      person.path.push([entry, hall], [entry, y], [x, y]);
      person.destination = id;
      notify();
      return true;
    }

    function advance(person, distance) {
      while (person.path.length && distance > 0) {
        const [x, y] = person.path[0];
        const dx = x - person.x;
        const dy = y - person.y;
        const left = Math.hypot(dx, dy);
        if (distance < left) {
          person.x += dx * distance / left;
          person.y += dy * distance / left;
          person.phase += distance;
          return false;
        }
        person.x = x;
        person.y = y;
        person.phase += left;
        distance -= left;
        person.path.shift();
        if (!person.path.length) {
          person.room = person.destination;
          person.destination = null;
          return true;
        }
      }
      return false;
    }

    function step(dt) {
      if (destroyed || isPaused()) return;
      nextMove -= dt;
      if (nextMove <= 0) {
        const index = cycle++ % people.length;
        const person = people[index];
        if (!person.destination) {
          const position = ids.indexOf(person.room);
          movePerson(index, ids[(position + 1 + cycle % 2) % ids.length]);
        }
        nextMove = 3450;
      }
      let moved = false;
      for (const person of people) moved = advance(person, dt * 0.077) || moved;
      if (moved) notify();
      draw();
    }

    function select(index) {
      if (destroyed || !Number.isInteger(index) || !people[index]) return false;
      selected = index;
      draw();
      notify();
      return true;
    }

    function setPaused(value) {
      if (destroyed || paused === Boolean(value)) return;
      paused = Boolean(value);
      draw();
      notify();
      schedule();
    }

    function selectAtPoint(event) {
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const x = (event.clientX - rect.left) * canvas.width / rect.width;
      const y = (event.clientY - rect.top) * canvas.height / rect.height;
      const index = people.findIndex(person => Math.abs(person.x - x) < 9 && y >= person.y - 15 && y <= person.y + 5);
      if (index >= 0) select(index);
    }
    canvas.addEventListener('click', selectAtPoint);
    draw();
    queueMicrotask(notify);

    return {
      select, move: id => movePerson(selected, id), setPaused,
      isPaused, step, notify,
      destroy() {
        destroyed = true;
        canvas.removeEventListener('click', selectAtPoint);
      },
    };
  }

  const defaultPalette = {
    accent: '#ff503d',
    halo: '#7b1a18',
    dots: ['#ff321d', '#f54215', '#fe5919', '#fa801c', '#e7ab13', '#edcf20'],
    falloff: ['#ffc5b5e6', '#ff7650c5', '#d7292464', '#7b1a1833', '#0000'],
    rings: ['#fa321e', '#dca030', '#f25d22'],
  };
  const stateIntensity = { idle: .88, listen: 1, think: .94, speak: 1, stopped: .28 };
  const stateNames = {
    idle: 'idle', listening: 'listen', thinking: 'think', speaking: 'speak',
    listen: 'listen', think: 'think', speak: 'speak', working: 'think', stopped: 'stopped',
  };
  const dust = Array.from({ length: 680 }, (_, index) => {
    const y = 1 - 2 * (index + .5) / 680;
    const radius = Math.sqrt(1 - y * y);
    const theta = index * 2.39996322972865;
    return {
      x: Math.cos(theta) * radius, y, z: Math.sin(theta) * radius,
      size: index % 13 === 0 ? 2 : .85, faint: index % 31 < 4,
    };
  });

  function tint(accent, target, amount) {
    const channels = accent.slice(1).match(/../g).map(channel => {
      const value = parseInt(channel, 16);
      return Math.round(value + (target - value) * amount).toString(16).padStart(2, '0');
    });
    return '#' + channels.join('');
  }

  function colorPalette(accent) {
    const white = amount => tint(accent, 255, amount);
    const black = amount => tint(accent, 0, amount);
    return {
      accent, halo: black(.50),
      dots: [black(.23), accent, white(.13), white(.28), white(.45), white(.65)],
      falloff: [white(.80) + 'e6', white(.27) + 'c5', black(.12) + '64', black(.50) + '33', '#0000'],
      rings: [accent, white(.42), white(.17)],
    };
  }

  function sizeCanvas(canvas, ctx) {
    if (!ctx) return null;
    const bounds = canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return null;
    const ratio = Math.min(window.devicePixelRatio || 1, 1.6);
    const width = Math.max(1, Math.round(bounds.width * ratio));
    const height = Math.max(1, Math.round(bounds.height * ratio));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    return bounds;
  }

  function mount(root, { onOfficeChange } = {}) {
    const doc = root.ownerDocument;
    const reactor = root.querySelector('.reactor');
    const scene = root.querySelector('#reactor-canvas');
    const links = root.querySelector('#core-links');
    const nodes = [...root.querySelectorAll('.core-option[data-home-tool]')];
    const officeCanvas = root.querySelector('#office-map');
    const coreContext = scene?.getContext('2d');
    const linksContext = links?.getContext('2d');
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let palette = defaultPalette;
    let state = 'idle';
    let frame = null;
    let previous = 0;
    let time = 0;
    let sceneRect = null;
    let linkRect = null;
    let destroyed = false;

    const office = createOffice(officeCanvas, onOfficeChange, schedule, reduced);
    const coreVisible = () => !!coreContext && !scene.closest('[hidden]') &&
      !reactor?.querySelector('video:not([hidden])');
    const officeVisible = () => !!office && !officeCanvas.closest('[hidden]');
    const canDraw = () => !destroyed && root.isConnected && !doc.hidden;
    const animated = () => canDraw() && !reduced.matches &&
      ((coreVisible() && state !== 'stopped') || (officeVisible() && !office.isPaused()));

    function drawLinks() {
      if (!linkRect?.width || !reactor || links.closest('[hidden]')) return;
      const ctx = linksContext;
      const target = reactor.getBoundingClientRect();
      const end = target.left - linkRect.left + 1;
      const mid = target.top + target.height * .5 - linkRect.top;
      ctx.clearRect(0, 0, linkRect.width, linkRect.height);
      nodes.forEach((node, index) => {
        const bound = node.getBoundingClientRect();
        const trace = node.style.getPropertyValue('--trace').trim();
        const x = bound.right - linkRect.left - 9;
        const y = bound.top - linkRect.top + bound.height / 2;
        if (!bound.width || end <= x || !/^#[0-9a-f]{6}$/i.test(trace)) return;
        const targetY = mid + (index - (nodes.length - 1) / 2) * 11;
        const elbow = x + (end - x) * .33;
        const join = Math.min(end - 5, elbow + Math.abs(targetY - y) * .83);
        const points = [[x, y], [elbow, y], [join, targetY], [end, targetY]];
        ctx.strokeStyle = trace;
        ctx.lineWidth = 1.2;
        ctx.shadowColor = trace;
        ctx.shadowBlur = state === 'stopped' ? 0 : 5;
        ctx.globalAlpha = state === 'stopped' ? .38 : .94;
        ctx.beginPath();
        ctx.moveTo(x, y);
        for (const [px, py] of points.slice(1)) ctx.lineTo(px, py);
        ctx.stroke();
        ctx.fillStyle = trace;
        ctx.fillRect(x - 2, y - 2, 4, 4);
        for (const [px, py] of points.slice(1, -1)) ctx.fillRect(px - 1, py - 1, 2, 2);
        if (state !== 'stopped' && !reduced.matches) {
          const fraction = ((time / 1200 + .25 * index) % 1) * 3;
          const leg = Math.min(2, Math.floor(fraction));
          const part = fraction - leg;
          const [ax, ay] = points[leg];
          const [bx, by] = points[leg + 1];
          ctx.fillRect(ax + (bx - ax) * part - 1, ay + (by - ay) * part - 1, 3, 3);
        }
        ctx.globalAlpha = 1;
        ctx.shadowBlur = 0;
      });
    }

    function drawReactor() {
      if (!sceneRect?.width || !sceneRect.height || !coreVisible()) return;
      const ctx = coreContext;
      const { width, height } = sceneRect;
      const cx = width * .51;
      const cy = height * .43;
      const radius = Math.min(width * .28, height * .30);
      const intensity = stateIntensity[state];
      ctx.clearRect(0, 0, width, height);
      ctx.save();
      ctx.globalAlpha = intensity;
      const flare = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius * 1.8);
      [0, .07, .28, .61, 1].forEach((stop, index) => flare.addColorStop(stop, palette.falloff[index]));
      ctx.fillStyle = flare;
      ctx.fillRect(0, 0, width, height);
      const angle = time / 2800;
      const cosine = Math.cos(angle);
      const sine = Math.sin(angle);
      for (const dot of dust) {
        const z = dot.z * cosine - dot.x * sine;
        const x = dot.x * cosine + dot.z * sine;
        const scale = radius * (1 + z * .09);
        const shade = Math.min(5, Math.max(0, Math.round((x - dot.y + 1.8) * 1.45)));
        ctx.fillStyle = palette.dots[shade];
        ctx.globalAlpha = intensity * .71 * (1 + z * .35) * (dot.faint ? .34 : 1);
        ctx.fillRect(cx + x * scale, cy + dot.y * scale, dot.size, dot.size);
      }
      ctx.globalAlpha = intensity * .52;
      [-.44, .31, -.16].forEach((tilt, index) => {
        ctx.strokeStyle = palette.rings[index];
        ctx.lineWidth = index === 1 ? 1 : .8;
        ctx.beginPath();
        ctx.ellipse(cx, cy, radius * (1.22 - index * .08), radius * (.32 + index * .05), tilt, 0, Math.PI * 2);
        ctx.stroke();
      });
      ctx.restore();
    }

    function schedule() {
      if (!animated()) {
        if (frame !== null) window.cancelAnimationFrame(frame);
        frame = null;
        previous = 0;
        return;
      }
      if (frame === null) frame = window.requestAnimationFrame(tick);
    }

    function tick(now) {
      frame = null;
      if (!root.isConnected) {
        destroy();
        return;
      }
      if (!animated()) return;
      if (!previous || now - previous >= 31) {
        const delta = previous ? Math.min(now - previous, 60) : 0;
        previous = now;
        if (state !== 'stopped' && coreVisible()) {
          time += delta;
          drawLinks();
          drawReactor();
        }
        if (officeVisible()) office.step(delta);
      }
      schedule();
    }

    function refresh() {
      if (!root.isConnected) {
        destroy();
        return;
      }
      if (canDraw()) {
        sceneRect = sizeCanvas(scene, coreContext);
        linkRect = sizeCanvas(links, linksContext);
        drawLinks();
        drawReactor();
      }
      schedule();
    }

    function setTask(kind) {
      if (destroyed || !reactor) return;
      const trace = nodes.find(node => node.dataset.homeTool === kind)?.style.getPropertyValue('--trace').trim();
      if (/^#[0-9a-f]{6}$/i.test(trace || '')) {
        palette = colorPalette(trace);
        reactor.dataset.reactorTask = kind;
        reactor.style.setProperty('--reactor-accent', palette.accent);
        reactor.style.setProperty('--reactor-glow', palette.halo);
      } else {
        palette = defaultPalette;
        delete reactor.dataset.reactorTask;
        reactor.style.removeProperty('--reactor-accent');
        reactor.style.removeProperty('--reactor-glow');
      }
      if (canDraw()) drawReactor();
    }

    function setState(next) {
      if (destroyed) return;
      const name = Object.hasOwn(stateNames, next) ? stateNames[next] : 'idle';
      if (state === name) return;
      state = name;
      if (reactor) reactor.dataset.state = name;
      if (canDraw()) {
        drawLinks();
        drawReactor();
      }
      schedule();
    }

    function preferencesChanged() {
      office?.notify();
      refresh();
    }

    const observer = new window.ResizeObserver(refresh);
    const visibility = new window.MutationObserver(refresh);
    for (const element of [reactor, links, officeCanvas]) {
      if (element) observer.observe(element);
    }
    visibility.observe(root, { subtree: true, attributes: true, attributeFilter: ['hidden'] });
    doc.addEventListener('visibilitychange', refresh);
    reduced.addEventListener('change', preferencesChanged);
    if (reactor) reactor.dataset.state = state;
    refresh();

    function destroy() {
      if (destroyed) return;
      destroyed = true;
      schedule();
      observer.disconnect();
      visibility.disconnect();
      doc.removeEventListener('visibilitychange', refresh);
      reduced.removeEventListener('change', preferencesChanged);
      office?.destroy();
    }

    return { setTask, setState, office, destroy };
  }

  window.JarvisHomeVisuals = { mount };
})();
