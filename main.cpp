#include <SoapySDR/Device.h>
#include <SoapySDR/Formats.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <complex.h>

int main(void)
{
    // Создание сущности устройства
    SoapySDRKwargs args = {};
    SoapySDRKwargs_set(&args, "driver", "plutosdr");
    if (1) {
        SoapySDRKwargs_set(&args, "uri", "usb:");
    } else {
        SoapySDRKwargs_set(&args, "uri", "ip:192.168.2.1");
    }
    SoapySDRKwargs_set(&args, "direct", "1");
    SoapySDRKwargs_set(&args, "timestamp_every", "1920");
    SoapySDRKwargs_set(&args, "loopback", "0");

    SoapySDRDevice *sdr = SoapySDRDevice_make(&args);
    SoapySDRKwargs_clear(&args);

    if (sdr == NULL)
    {
        printf("SoapySDRDevice_make fail: %s\n", SoapySDRDevice_lastError());
        return EXIT_FAILURE;
    }

    // Настраиваем приёмник (RX)
    if (SoapySDRDevice_setSampleRate(sdr, SOAPY_SDR_RX, 0, 1e6) != 0)
    {
        printf("setSampleRate rx fail: %s\n", SoapySDRDevice_lastError());
    }
    if (SoapySDRDevice_setFrequency(sdr, SOAPY_SDR_RX, 0, 800e6, NULL) != 0)
    {
        printf("setFrequency rx fail: %s\n", SoapySDRDevice_lastError());
    }

    // Каналы
    size_t channels[] = {0}; // только один канал для приёма
    size_t channel_count = sizeof(channels) / sizeof(channels[0]);

    // Настройка RX-стрима
    SoapySDRStream *rxStream = SoapySDRDevice_setupStream(
        sdr, SOAPY_SDR_RX, SOAPY_SDR_CS16, channels, channel_count, NULL);
    if (rxStream == NULL)
    {
        printf("setupStream rx fail: %s\n", SoapySDRDevice_lastError());
        SoapySDRDevice_unmake(sdr);
        return EXIT_FAILURE;
    }

    // Усиление приёмника
    if (SoapySDRDevice_setGain(sdr, SOAPY_SDR_RX, channels[0], 30.0) != 0)
    {
        printf("setGain rx fail: %s\n", SoapySDRDevice_lastError());
    }

    // Получаем MTU (размер буфера)
    size_t rx_mtu = SoapySDRDevice_getStreamMTU(sdr, rxStream);
    printf("MTU - RX: %lu\n", rx_mtu);

    // Буфер для приёма: 2 * mtu int16 (I и Q чередуются)
    int16_t *rx_buffer = (int16_t *)malloc(2 * rx_mtu * sizeof(int16_t));
    if (rx_buffer == NULL)
    {
        printf("malloc fail\n");
        SoapySDRDevice_closeStream(sdr, rxStream);
        SoapySDRDevice_unmake(sdr);
        return EXIT_FAILURE;
    }

    // Активируем RX-стрим
    SoapySDRDevice_activateStream(sdr, rxStream, 0, 0, 0);

    printf("Start RX test...\n");
    const long timeoutUs = 400000; // 

    // Открываем файл для записи принятых сэмплов
    FILE *file = fopen("rxdata.pcm", "w");
    if (file == NULL)
    {
        printf("fopen fail\n");
        free(rx_buffer);
        SoapySDRDevice_deactivateStream(sdr, rxStream, 0, 0);
        SoapySDRDevice_closeStream(sdr, rxStream);
        SoapySDRDevice_unmake(sdr);
        return EXIT_FAILURE;
    }

    // При первом запуске очищаем буфер от мусора (прогреваем поток)
    printf("Flushing RX buffers...\n");
    for (size_t buffers_read = 0; buffers_read < 128; /* in loop */)
    {
        void *buffs[] = {rx_buffer};
        int flags = 0;
        long long timeNs = 0;

        int sr = SoapySDRDevice_readStream(sdr, rxStream, buffs, rx_mtu,
                                           &flags, &timeNs, timeoutUs);
        if (sr < 0)
        {
            // Пропускаем ошибку (скорее всего таймаут)
            continue;
        }
        buffers_read++;
    }

    long long last_time = 0;

    // Количество итераций приёма
    size_t iteration_count = 2000;

    for (size_t buffers_read = 0; buffers_read < iteration_count; buffers_read++)
    {
        void *rx_buffs[] = {rx_buffer};
        int flags = 0;
        long long timeNs = 0;

        int sr = SoapySDRDevice_readStream(sdr, rxStream, rx_buffs, rx_mtu,
                                           &flags, &timeNs, timeoutUs);
        if (sr < 0)
        {
            printf("readStream fail or timeout: %i\n", sr);
            continue;
        }

        // Информация о буфере
        printf("Buffer: %lu - Samples: %i, Flags: %i, Time: %lli, TimeDiff: %lli\n",
               buffers_read, sr, flags, timeNs, timeNs - last_time);

        // Пишем принятые сэмплы в файл
        fwrite(rx_buffer, 2 * rx_mtu * sizeof(int16_t), 1, file);

        last_time = timeNs;
    }

    fclose(file);

    // Останавливаем и закрываем стрим
    SoapySDRDevice_deactivateStream(sdr, rxStream, 0, 0);
    SoapySDRDevice_closeStream(sdr, rxStream);

    // Освобождаем устройство
    SoapySDRDevice_unmake(sdr);

    free(rx_buffer);

    printf("RX test complete!\n");

    return EXIT_SUCCESS;
}