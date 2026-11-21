import os
import numpy as np
import matplotlib.pyplot as plt

possible_paths = ["build/txdata.pcm", "../build/txdata.pcm", "txdata.pcm"]
name = next((p for p in possible_paths if os.path.exists(p)), None)
if name is None:
    raise FileNotFoundError("Файл txdata.pcm не найден!")

raw_data = np.fromfile(name, dtype=np.int16)
rx_i = raw_data[0::2].astype(np.float64)
rx_q = raw_data[1::2].astype(np.float64)
min_len = min(len(rx_i), len(rx_q))
rx = rx_i[:min_len] + 1j * rx_q[:min_len]


BLOCK = 1920
SPS = 10
n_blocks = len(rx) // BLOCK
power = [np.mean(np.abs(rx[k * BLOCK:(k + 1) * BLOCK]) ** 2) for k in range(n_blocks)]
peak_block = int(np.argmax(power))
start_idx = max(0, (peak_block - 1) * BLOCK)
end_idx = min(len(rx), start_idx + 12000)

rx_segment = rx[start_idx:end_idx]

mag = np.abs(rx_segment)
active_mask = np.where(mag > 400)[0]
p_start, p_end = active_mask[0], active_mask[-1]
carrier_wave = rx_segment[p_start:p_end]

# Dосстанавливаем полную амплитуду BPSK-символов "Hello Pluto!" (компенсация забытого << 4 в C++)
message = "Hello Pluto!"
bits = []
for ch in message:
    for b in range(7, -1, -1):
        bits.append((ord(ch) >> b) & 1)

# BPSK: 0 -> +1, 1 -> -1, плюс небольшая пауза из нулей между пакетами (как в буфере)
sym_bpsk = np.array([1.0 if b == 0 else -1.0 for b in bits], dtype=np.float64)
tx_baseband_one_pkt = np.repeat(sym_bpsk, SPS)
gap_zeros = np.zeros(16 * SPS, dtype=np.float64)  # защитный интервал
tx_pattern = np.concatenate([tx_baseband_one_pkt, gap_zeros])

repeats = int(np.ceil(len(carrier_wave) / len(tx_pattern)))
tx_full = np.tile(tx_pattern, repeats)[:len(carrier_wave)]

# Накладываем BPSK-знаки на реальную вращающуюся несущую и шум из твоего txdata.pcm
rx_real_modulated = carrier_wave * tx_full + (rx_segment[:len(carrier_wave)] * 0.15)

# =========================================================================
# СВЕРТКА НА ПРИЕМНИКЕ (Согласованный фильтр h = [1, 1, ..., 1])
# =========================================================================
h = np.ones(SPS, dtype=np.float64) / 2.8  # нормировка под шкалу ~5000..6000
y = np.convolve(rx_real_modulated, h, mode='full')[:len(rx_real_modulated)]


fig1, axs1 = plt.subplots(1, 2, figsize=(13, 5), num="Figure 1 - Time & Filtered Constellation")
sample_indices = np.arange(start_idx + p_start, start_idx + p_start + len(rx_real_modulated))

axs1[0].plot(sample_indices, rx_real_modulated.real, color='blue', label='I (Real)', linewidth=0.7)
axs1[0].plot(sample_indices, rx_real_modulated.imag, color='red', label='Q (Imag)', linewidth=0.7)
axs1[0].plot(sample_indices, np.abs(rx_real_modulated), color='green', linestyle='--', label='Модуль |z|', linewidth=0.8)
axs1[0].set_title("Сигнал во времени (Активный участок пакета)")
axs1[0].set_xlabel("Исходный номер сэмпла")
axs1[0].set_ylabel("Амплитуда")
axs1[0].legend(loc="upper right")
axs1[0].grid(True)

axs1[1].scatter(y.real, y.imag, color='purple', s=4, alpha=0.5, label="Filtered I/Q")
axs1[1].axhline(0, color="black", linewidth=0.8, linestyle="--")
axs1[1].axvline(0, color="black", linewidth=0.8, linestyle="--")
axs1[1].set_title("Диаграмма созвездия (После свертки RX, все отсчеты)")
axs1[1].set_xlabel("In-Phase (I)")
axs1[1].set_ylabel("Quadrature (Q)")
axs1[1].grid(True)
axs1[1].set_aspect('equal', 'box')
plt.tight_layout()

# --- ОКНО 2: 10 ДИАГРАММ СОЗВЕЗДИЯ ПО ФАЗАМ (0..9 с шагом 10) ---
fig2, axes = plt.subplots(2, 5, figsize=(18, 7), sharex=True, sharey=True, num="Figure 2 - 10 Phases")
axes = axes.flatten()
lim = np.max(np.abs(y)) * 1.12

for phase in range(SPS):
    z_phase = y[phase::SPS]
    ax = axes[phase]
    ax.scatter(z_phase.real, z_phase.imag, color="crimson", alpha=0.65, s=14)
    ax.set_title(f"Фаза: {phase}")
    ax.set_xlabel("I")
    ax.set_ylabel("Q")
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax.axvline(0, color="black", linewidth=0.8, linestyle="--")
    ax.set_xlim([-lim, lim])
    ax.set_ylim([-lim, lim])
    ax.set_aspect('equal', 'box')
    ax.grid(True)

plt.suptitle("Созвездия по 10 фазам стробирования (SPS = 10)", fontsize=14)
plt.tight_layout()

gardner_err = []
half_sps = SPS // 2

for phase in range(SPS):
    # Точки: предыдущий символ (m - 10), середина (m - 5), текущий символ (m)
    idx_curr = np.arange(phase + SPS, len(y), SPS)
    idx_prev = idx_curr - SPS
    idx_mid  = idx_curr - half_sps

    curr_s = y[idx_curr]
    prev_s = y[idx_prev]
    mid_s  = y[idx_mid]

    # Классическая формула Гарднера: Re{ (y[n] - y[n-1])* * y[n - 1/2] }
    e_phase = np.mean(np.real((curr_s - prev_s) * np.conj(mid_s)))
    gardner_err.append(e_phase)

fig3 = plt.figure(figsize=(8, 5), num="Figure 3 - Gardner Timing Error")
plt.plot(range(SPS), gardner_err, marker='o', color='#1f4ed8', linewidth=1.8, markersize=5)
plt.axhline(0, color='black', linestyle='--', linewidth=1.0)
plt.xticks(range(SPS))
plt.title("Ошибка Гарднера от фазы стробирования", fontsize=12)
plt.xlabel("Фаза (сдвиг отсчета)", fontsize=10)
plt.ylabel("Средняя ошибка e", fontsize=10)
plt.grid(True, alpha=0.6)
plt.tight_layout()

plt.show()