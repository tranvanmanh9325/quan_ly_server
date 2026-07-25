package com.miniserver.dashboard.controller;

import com.miniserver.dashboard.model.ServerMetric;
import com.miniserver.dashboard.repository.ServerMetricRepository;
import com.miniserver.dashboard.service.SshService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class MetricsControllerTest {

    @Mock
    private SshService sshService;

    @Mock
    private ServerMetricRepository metricRepository;

    @InjectMocks
    private MetricsController metricsController;

    @BeforeEach
    void setUp() {
    }

    @Test
    @DisplayName("getHistory - should return list of metrics reversed")
    void testGetHistory() {
        ServerMetric m1 = new ServerMetric(LocalDateTime.now().minusMinutes(2), 10.0, 20.0);
        ServerMetric m2 = new ServerMetric(LocalDateTime.now().minusMinutes(1), 15.0, 25.0);
        when(metricRepository.findTop100ByOrderByTimestampDesc()).thenReturn(List.of(m2, m1));

        List<ServerMetric> result = metricsController.getHistory();

        assertEquals(2, result.size());
        assertEquals(m1, result.get(0));
        assertEquals(m2, result.get(1));
        verify(metricRepository, times(1)).findTop100ByOrderByTimestampDesc();
    }

    @Test
    @DisplayName("getCpu - should execute top command and return safe data")
    void testGetCpu() {
        when(sshService.executeCommand(anyString())).thenReturn("%Cpu(s): 10.0 us, 5.0 sy, 0.0 ni, 85.0 id");

        Map<String, String> res = metricsController.getCpu();

        assertNotNull(res);
        assertTrue(res.containsKey("data"));
        assertTrue(res.get("data").contains("85.0 id"));
    }

    @Test
    @DisplayName("getDockerContainers - should parse docker ps format correctly")
    void testGetDockerContainers() {
        String mockOutput = "abc123|app-web|nginx:alpine|Up 2 hours|0.0.0.0:80->80/tcp";
        when(sshService.executeCommand(anyString())).thenReturn(mockOutput);

        Map<String, Object> res = metricsController.getDockerContainers();

        assertEquals("RUNNING", res.get("status"));
        @SuppressWarnings("unchecked")
        List<Map<String, String>> containers = (List<Map<String, String>>) res.get("data");
        assertEquals(1, containers.size());
        assertEquals("abc123", containers.get(0).get("id"));
        assertEquals("app-web", containers.get(0).get("name"));
    }

    @Test
    @DisplayName("getDockerLogs - should reject invalid container ID")
    void testGetDockerLogs_InvalidId() {
        Map<String, String> res = metricsController.getDockerLogs("rm -rf ; echo", 100);

        assertEquals("error", res.get("status"));
        assertEquals("Invalid container ID or name", res.get("data"));
        verify(sshService, never()).executeCommand(anyString());
    }

    @Test
    @DisplayName("getDockerLogs - should fetch logs for valid container ID")
    void testGetDockerLogs_Success() {
        when(sshService.executeCommand(anyString())).thenReturn("2026-07-24 Log line 1\n2026-07-24 Log line 2");

        Map<String, String> res = metricsController.getDockerLogs("web_app", 50);

        assertNotNull(res);
        assertTrue(res.get("data").contains("Log line 1"));
        verify(sshService).executeCommand(contains("docker logs --tail 50 web_app"));
    }

    @Test
    @DisplayName("controlDocker - should reject invalid action")
    void testControlDocker_InvalidAction() {
        Map<String, String> res = metricsController.controlDocker("my_container", "destroy");

        assertEquals("error", res.get("status"));
        assertEquals("Invalid action", res.get("message"));
    }

    @Test
    @DisplayName("killProcess - should reject PIDs under 1000")
    void testKillProcess_SystemPid() {
        Map<String, String> res = metricsController.killProcess("1");

        assertEquals("error", res.get("status"));
        assertTrue(res.get("message").contains("Cannot kill system processes"));
    }

    @Test
    @DisplayName("executeCommand - should block destructive commands")
    void testExecuteCommand_Blocked() {
        Map<String, String> res = metricsController.executeCommand("rm -rf /");

        assertEquals("error", res.get("status"));
        assertTrue(res.get("message").contains("Security Alert"));
    }

    @Test
    @DisplayName("getDockerStats - should return container stats string")
    void testGetDockerStats() {
        when(sshService.executeCommand(anyString())).thenReturn("abc123|web_app|2.5%|45.2MiB / 1GiB|1.2kB / 5.4kB");

        Map<String, String> res = metricsController.getDockerStats();

        assertNotNull(res);
        assertTrue(res.get("data").contains("web_app"));
    }
}