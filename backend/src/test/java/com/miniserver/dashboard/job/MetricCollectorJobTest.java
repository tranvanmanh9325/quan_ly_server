package com.miniserver.dashboard.job;

import com.miniserver.dashboard.model.ServerMetric;
import com.miniserver.dashboard.repository.ServerMetricRepository;
import com.miniserver.dashboard.service.SshService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class MetricCollectorJobTest {

    @Mock
    private SshService sshService;

    @Mock
    private ServerMetricRepository metricRepository;

    @InjectMocks
    private MetricCollectorJob metricCollectorJob;

    @Test
    @DisplayName("collectMetrics - should parse CPU, RAM, Disk and save to repository")
    void testCollectMetrics_Success() {
        // Command now produces 3 sections: cpu --- ram --- disk (df / tail -1)
        String mockOutput = "%Cpu(s): 12.5 us, 2.5 sy, 0.0 ni, 85.0 id\n"
                + "---\n"
                + "Mem: 16000 4000 8000 0 4000 8000\n"
                + "---\n"
                // df / data line (Filesystem 1K-blocks Used Available Use% Mountpoint)
                + "/dev/sda1 20480000 9830400 10649600 48% /";
        when(sshService.executeCommand(anyString())).thenReturn(mockOutput);

        metricCollectorJob.collectMetrics();

        ArgumentCaptor<ServerMetric> captor = ArgumentCaptor.forClass(ServerMetric.class);
        verify(metricRepository, times(1)).save(captor.capture());

        ServerMetric saved = captor.getValue();
        assertEquals(15.0, saved.getCpuPercent());   // 100 - 85.0
        assertNotNull(saved.getRamPercent());
        assertEquals(48.0, saved.getDiskPercent());  // parsed from "48%"
    }

    @Test
    @DisplayName("collectMetrics - should parse disk correctly when df outputs header + data line")
    void testCollectMetrics_DiskWithHeader() {
        String mockOutput = "%Cpu(s):  6.0 us,  2.0 sy,  0.0 ni, 92.0 id\n"
                + "---\n"
                + "Mem: 8000 2000 4000 0 2000 4000\n"
                + "---\n"
                // df with header (some distros include it even for tail -1)
                + "Filesystem     1K-blocks    Used Available Use% Mounted on\n"
                + "/dev/sda1       20480000 9830400  10649600  48% /";
        when(sshService.executeCommand(anyString())).thenReturn(mockOutput);

        metricCollectorJob.collectMetrics();

        ArgumentCaptor<ServerMetric> captor = ArgumentCaptor.forClass(ServerMetric.class);
        verify(metricRepository, times(1)).save(captor.capture());
        assertEquals(48.0, captor.getValue().getDiskPercent());
    }

    @Test
    @DisplayName("collectMetrics - should handle SSH error gracefully without throwing exception")
    void testCollectMetrics_SshError() {
        when(sshService.executeCommand(anyString())).thenReturn("Lỗi SSH");

        metricCollectorJob.collectMetrics();

        verify(metricRepository, never()).save(any(ServerMetric.class));
    }

    @Test
    @DisplayName("collectMetrics - should still save when disk part is missing/unparseable")
    void testCollectMetrics_DiskNull() {
        // disk part missing — only 2 separators, 3rd section empty
        String mockOutput = "%Cpu(s):  5.0 us, 1.0 sy, 0.0 ni, 94.0 id\n"
                + "---\n"
                + "Mem: 8000 2000 4000 0 2000 4000\n"
                + "---\n"
                + ""; // empty disk section → parseDisk returns null
        when(sshService.executeCommand(anyString())).thenReturn(mockOutput);

        metricCollectorJob.collectMetrics();

        // cpuPercent + ramPercent are valid → should save with diskPercent = null
        ArgumentCaptor<ServerMetric> captor = ArgumentCaptor.forClass(ServerMetric.class);
        verify(metricRepository, times(1)).save(captor.capture());
        assertNull(captor.getValue().getDiskPercent());
    }
}