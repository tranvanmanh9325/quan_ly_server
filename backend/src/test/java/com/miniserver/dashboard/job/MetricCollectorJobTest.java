package com.miniserver.dashboard.job;

import com.miniserver.dashboard.model.ServerMetric;
import com.miniserver.dashboard.repository.ServerMetricRepository;
import com.miniserver.dashboard.service.SshService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

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
    @DisplayName("collectMetrics - should parse CPU and RAM and save to repository")
    void testCollectMetrics_Success() {
        String mockOutput = "%Cpu(s): 12.5 us, 2.5 sy, 0.0 ni, 85.0 id\n---\nMem: 16000 4000 8000 0 4000 8000";
        when(sshService.executeCommand(anyString())).thenReturn(mockOutput);

        metricCollectorJob.collectMetrics();

        verify(metricRepository, times(1)).save(any(ServerMetric.class));
    }

    @Test
    @DisplayName("collectMetrics - should handle SSH error gracefully without throwing exception")
    void testCollectMetrics_SshError() {
        when(sshService.executeCommand(anyString())).thenReturn("Lỗi SSH");

        metricCollectorJob.collectMetrics();

        verify(metricRepository, never()).save(any(ServerMetric.class));
    }
}