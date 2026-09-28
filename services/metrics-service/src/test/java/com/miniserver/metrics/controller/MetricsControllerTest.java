package com.miniserver.metrics.controller;

import com.miniserver.metrics.repository.ServerMetricRepository;
import com.miniserver.metrics.service.ActiveClientRegistry;
import com.miniserver.metrics.service.SshService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.*;

/**
 * Unit Test Suite for {@link MetricsController}.
 * Focuses on Milestone 1: Docker metadata enrichment and Compose project grouping parsing.
 * Uses pure JUnit 5 and Mockito without Spring Context for sub-second execution.
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("MetricsController Unit Tests")
class MetricsControllerTest {

    @Mock
    private SshService sshService;

    @Mock
    private ServerMetricRepository metricRepository;

    @Mock
    private ActiveClientRegistry activeClientRegistry;

    private MetricsController metricsController;

    @BeforeEach
    void setUp() {
        // Explicit instantiation ensures pristine in-memory caches per test execution
        metricsController = new MetricsController(sshService, metricRepository, activeClientRegistry);
    }

    @Nested
    @DisplayName("Tests for GET /api/metrics/docker (getDockerContainers)")
    class GetDockerContainersTests {

        @Test
        @DisplayName("1. Parse Compose containers: All 9 fields populated correctly")
        @SuppressWarnings("unchecked")
        void testGetDockerContainers_StandardComposeContainers_AllFieldsPopulated() {
            // Given: Output from `docker ps -a` with 2 compose containers
            String mockDockerPsOutput =
                "679e309f28d6|dashboard_metrics_service|quan_ly_server-metrics-service|Up 2 days (healthy)|0.0.0.0:8083->8083/tcp|quan_ly_server|metrics-service|/home/kirito/quan_ly_server|/home/kirito/quan_ly_server/docker-compose.yml\n" +
                "a1b2c3d4e5f6|dashboard_frontend|quan_ly_server-frontend|Up 2 days|0.0.0.0:3000->80/tcp|quan_ly_server|frontend|/home/kirito/quan_ly_server|/home/kirito/quan_ly_server/docker-compose.yml\n";

            when(sshService.executeCommand(argThat(cmd -> cmd != null && cmd.contains("docker ps -a") && !cmd.contains("===SEP==="))))
                .thenReturn(mockDockerPsOutput);

            // When: invoking controller endpoint
            Map<String, Object> response = metricsController.getDockerContainers();

            // Then: verify high-level response structure
            assertNotNull(response, "Response must not be null");
            assertEquals("RUNNING", response.get("status"), "Status must be RUNNING");
            assertTrue(response.get("data") instanceof List<?>, "Data must be a List");

            List<Map<String, String>> containers = (List<Map<String, String>>) response.get("data");
            assertEquals(2, containers.size(), "Should have parsed exactly 2 containers");

            // Verify container 0: metrics-service
            Map<String, String> c0 = containers.get(0);
            assertEquals("679e309f28d6", c0.get("id"));
            assertEquals("dashboard_metrics_service", c0.get("name"));
            assertEquals("quan_ly_server-metrics-service", c0.get("image"));
            assertEquals("Up 2 days (healthy)", c0.get("status"));
            assertEquals("0.0.0.0:8083->8083/tcp", c0.get("ports"));
            assertEquals("quan_ly_server", c0.get("project"));
            assertEquals("metrics-service", c0.get("service"));
            assertEquals("/home/kirito/quan_ly_server", c0.get("workingDir"));
            assertEquals("/home/kirito/quan_ly_server/docker-compose.yml", c0.get("configFiles"));

            // Verify container 1: frontend
            Map<String, String> c1 = containers.get(1);
            assertEquals("a1b2c3d4e5f6", c1.get("id"));
            assertEquals("dashboard_frontend", c1.get("name"));
            assertEquals("quan_ly_server-frontend", c1.get("image"));
            assertEquals("Up 2 days", c1.get("status"));
            assertEquals("0.0.0.0:3000->80/tcp", c1.get("ports"));
            assertEquals("quan_ly_server", c1.get("project"));
            assertEquals("frontend", c1.get("service"));
            assertEquals("/home/kirito/quan_ly_server", c1.get("workingDir"));
            assertEquals("/home/kirito/quan_ly_server/docker-compose.yml", c1.get("configFiles"));

            verify(sshService, times(1)).executeCommand(anyString());
        }

        @Test
        @DisplayName("2. Parse Standalone containers: Empty trailing compose fields preserved as empty strings")
        @SuppressWarnings("unchecked")
        void testGetDockerContainers_StandaloneContainers_EmptyTrailingFields() {
            // Given: Standalone containers without compose labels, resulting in trailing empty pipes
            String mockDockerPsOutput =
                "fedcba987654|redis-standalone|redis:alpine|Up 5 hours|0.0.0.0:6379->6379/tcp||||\n" +
                "112233445566|test-mysql|mysql:8.0|Exited (0) 1 hour ago|||||\n";

            when(sshService.executeCommand(argThat(cmd -> cmd != null && cmd.contains("docker ps -a") && !cmd.contains("===SEP==="))))
                .thenReturn(mockDockerPsOutput);

            // When
            Map<String, Object> response = metricsController.getDockerContainers();

            // Then
            assertNotNull(response);
            assertEquals("RUNNING", response.get("status"));
            List<Map<String, String>> containers = (List<Map<String, String>>) response.get("data");
            assertEquals(2, containers.size());

            // Container 0: Standalone redis (ports present, compose labels empty)
            Map<String, String> c0 = containers.get(0);
            assertEquals("fedcba987654", c0.get("id"));
            assertEquals("redis-standalone", c0.get("name"));
            assertEquals("redis:alpine", c0.get("image"));
            assertEquals("Up 5 hours", c0.get("status"));
            assertEquals("0.0.0.0:6379->6379/tcp", c0.get("ports"));
            assertEquals("", c0.get("project"), "Project must be empty string for standalone container");
            assertEquals("", c0.get("service"), "Service must be empty string for standalone container");
            assertEquals("", c0.get("workingDir"), "WorkingDir must be empty string for standalone container");
            assertEquals("", c0.get("configFiles"), "ConfigFiles must be empty string for standalone container");

            // Container 1: Standalone mysql (both ports and compose labels empty)
            Map<String, String> c1 = containers.get(1);
            assertEquals("112233445566", c1.get("id"));
            assertEquals("test-mysql", c1.get("name"));
            assertEquals("mysql:8.0", c1.get("image"));
            assertEquals("Exited (0) 1 hour ago", c1.get("status"));
            assertEquals("", c1.get("ports"), "Ports must be empty string when not bound");
            assertEquals("", c1.get("project"));
            assertEquals("", c1.get("service"));
            assertEquals("", c1.get("workingDir"));
            assertEquals("", c1.get("configFiles"));
        }

        @Test
        @DisplayName("3a. Docker not installed: DOCKER_NOT_FOUND outputs status NOT_INSTALLED")
        @SuppressWarnings("unchecked")
        void testGetDockerContainers_DockerNotFound_ReturnsNotInstalled() {
            // Given: Docker is not installed on target host
            when(sshService.executeCommand(argThat(cmd -> cmd != null && cmd.contains("docker ps -a") && !cmd.contains("===SEP==="))))
                .thenReturn("DOCKER_NOT_FOUND\n");

            // When
            Map<String, Object> response = metricsController.getDockerContainers();

            // Then
            assertNotNull(response);
            assertEquals("NOT_INSTALLED", response.get("status"));
            List<?> containers = (List<?>) response.get("data");
            assertNotNull(containers);
            assertTrue(containers.isEmpty(), "Containers list must be empty when Docker is not installed");
        }

        @Test
        @DisplayName("3b. Empty SSH output: returns status ERROR")
        @SuppressWarnings("unchecked")
        void testGetDockerContainers_EmptyOutput_ReturnsError() {
            // Given: Command returned empty or whitespace
            when(sshService.executeCommand(argThat(cmd -> cmd != null && cmd.contains("docker ps -a") && !cmd.contains("===SEP==="))))
                .thenReturn("   \n");

            // When
            Map<String, Object> response = metricsController.getDockerContainers();

            // Then
            assertNotNull(response);
            assertEquals("ERROR", response.get("status"));
            List<?> containers = (List<?>) response.get("data");
            assertNotNull(containers);
            assertTrue(containers.isEmpty());
        }

        @Test
        @DisplayName("3c. SSH error or null return: returns status ERROR")
        @SuppressWarnings("unchecked")
        void testGetDockerContainers_NullOutput_ReturnsError() {
            // Given: SSH command execution returned null
            when(sshService.executeCommand(argThat(cmd -> cmd != null && cmd.contains("docker ps -a") && !cmd.contains("===SEP==="))))
                .thenReturn(null);

            // When
            Map<String, Object> response = metricsController.getDockerContainers();

            // Then
            assertNotNull(response);
            assertEquals("ERROR", response.get("status"));
            List<?> containers = (List<?>) response.get("data");
            assertNotNull(containers);
            assertTrue(containers.isEmpty());
        }

        @Test
        @DisplayName("3d. SSH error message: returns status ERROR")
        @SuppressWarnings("unchecked")
        void testGetDockerContainers_SshErrorString_ReturnsError() {
            // Given: SSH command execution returned error message
            when(sshService.executeCommand(argThat(cmd -> cmd != null && cmd.contains("docker ps -a") && !cmd.contains("===SEP==="))))
                .thenReturn("Lỗi SSH (sau 3 lần thử): Connection timed out\n");

            // When
            Map<String, Object> response = metricsController.getDockerContainers();

            // Then
            assertNotNull(response);
            assertEquals("ERROR", response.get("status"));
            List<?> containers = (List<?>) response.get("data");
            assertNotNull(containers);
            assertTrue(containers.isEmpty());
        }
    }

    @Nested
    @DisplayName("Tests for getSlowMetrics() Docker Section Parsing")
    class SlowMetricsTests {

        @Test
        @DisplayName("4a. Parse compound slow metrics output: Mixed Compose and Standalone containers")
        @SuppressWarnings("unchecked")
        void testGetSlowMetrics_DockerParsing_MixedComposeAndStandalone() {
            // Given: Compound SSH output with Docker section followed by syslog
            String dockerPart =
                "679e309f28d6|dashboard_metrics_service|quan_ly_server-metrics-service|Up 2 days (healthy)|0.0.0.0:8083->8083/tcp|quan_ly_server|metrics-service|/home/kirito/quan_ly_server|/home/kirito/quan_ly_server/docker-compose.yml\n" +
                "fedcba987654|redis-standalone|redis:alpine|Up 5 hours|0.0.0.0:6379->6379/tcp||||\n";
            String logsPart = "Sep 28 21:00:00 kirito-server systemd[1]: Started Metrics Service Telemetry.\n";
            String compoundOutput = dockerPart + "===SEP===\n" + logsPart;

            when(sshService.executeCommand(argThat(cmd -> cmd != null && cmd.contains("===SEP===") && cmd.contains("docker ps -a"))))
                .thenReturn(compoundOutput);

            // When: invoke private getSlowMetrics() via ReflectionTestUtils
            Map<String, Object> result = ReflectionTestUtils.invokeMethod(metricsController, "getSlowMetrics");

            // Then
            assertNotNull(result);
            assertTrue(result.containsKey("docker"), "Result must contain 'docker'");
            assertTrue(result.containsKey("logs"), "Result must contain 'logs'");

            // Inspect docker section
            Map<String, Object> dockerMap = (Map<String, Object>) result.get("docker");
            assertEquals("RUNNING", dockerMap.get("status"));
            List<Map<String, String>> containers = (List<Map<String, String>>) dockerMap.get("data");
            assertEquals(2, containers.size());

            // Check Compose container
            Map<String, String> composeContainer = containers.get(0);
            assertEquals("679e309f28d6", composeContainer.get("id"));
            assertEquals("dashboard_metrics_service", composeContainer.get("name"));
            assertEquals("quan_ly_server", composeContainer.get("project"));
            assertEquals("metrics-service", composeContainer.get("service"));
            assertEquals("/home/kirito/quan_ly_server", composeContainer.get("workingDir"));
            assertEquals("/home/kirito/quan_ly_server/docker-compose.yml", composeContainer.get("configFiles"));

            // Check Standalone container
            Map<String, String> standaloneContainer = containers.get(1);
            assertEquals("fedcba987654", standaloneContainer.get("id"));
            assertEquals("redis-standalone", standaloneContainer.get("name"));
            assertEquals("", standaloneContainer.get("project"));
            assertEquals("", standaloneContainer.get("service"));
            assertEquals("", standaloneContainer.get("workingDir"));
            assertEquals("", standaloneContainer.get("configFiles"));

            // Check logs section preservation
            Map<String, String> logsMap = (Map<String, String>) result.get("logs");
            assertNotNull(logsMap);
            assertTrue(logsMap.get("data").contains("Started Metrics Service Telemetry"));
        }

        @Test
        @DisplayName("4b. getSlowMetrics() with DOCKER_NOT_FOUND in compound output")
        @SuppressWarnings("unchecked")
        void testGetSlowMetrics_DockerNotFound() {
            // Given: Compound output where docker command returns DOCKER_NOT_FOUND
            String compoundOutput = "DOCKER_NOT_FOUND\n===SEP===\nSep 28 syslog log line\n";

            when(sshService.executeCommand(argThat(cmd -> cmd != null && cmd.contains("===SEP===") && cmd.contains("docker ps -a"))))
                .thenReturn(compoundOutput);

            // When
            Map<String, Object> result = ReflectionTestUtils.invokeMethod(metricsController, "getSlowMetrics");

            // Then
            assertNotNull(result);
            Map<String, Object> dockerMap = (Map<String, Object>) result.get("docker");
            assertNotNull(dockerMap);
            assertEquals("NOT_INSTALLED", dockerMap.get("status"));
            List<?> containers = (List<?>) dockerMap.get("data");
            assertNotNull(containers);
            assertTrue(containers.isEmpty());
        }

        @Test
        @DisplayName("4c. getSlowMetrics() with SSH error string in compound output")
        @SuppressWarnings("unchecked")
        void testGetSlowMetrics_SshError() {
            // Given: Compound output where docker section contains SSH error
            String compoundOutput = "Lỗi SSH (sau 3 lần thử): auth fail\n===SEP===\n";

            when(sshService.executeCommand(argThat(cmd -> cmd != null && cmd.contains("===SEP===") && cmd.contains("docker ps -a"))))
                .thenReturn(compoundOutput);

            // When
            Map<String, Object> result = ReflectionTestUtils.invokeMethod(metricsController, "getSlowMetrics");

            // Then
            assertNotNull(result);
            Map<String, Object> dockerMap = (Map<String, Object>) result.get("docker");
            assertNotNull(dockerMap);
            assertEquals("ERROR", dockerMap.get("status"));
            List<?> containers = (List<?>) dockerMap.get("data");
            assertNotNull(containers);
            assertTrue(containers.isEmpty());
        }
    }

    // =========================================================================
    // MILESTONE 2: DOCKER ENV MANAGEMENT & PROJECT CONTROL UNIT TESTS
    // =========================================================================

    @Nested
    @DisplayName("Tests for GET /api/metrics/docker/env (getDockerEnv)")
    class GetDockerEnvTests {

        @Test
        @DisplayName("1. Read .env success with backup present: Decodes Base64 UTF-8 correctly")
        void testDockerEnv_Get_Success() {
            String rawEnvContent = "POSTGRES_PASSWORD=kirito_secret_2026\nJWT_SECRET=super_jwt_token_metrics\nPORT=8083\nCOMMENT=Tiếng Việt UTF-8\n";
            String base64Content = Base64.getEncoder().encodeToString(rawEnvContent.getBytes(StandardCharsets.UTF_8));
            String mockSshOutput = base64Content + "\n===ENV_SEP===\n1\n";

            when(sshService.executeCommand(argThat(cmd -> 
                cmd != null && cmd.contains("/home/kirito/quan_ly_server/.env") && cmd.contains("base64")
            ))).thenReturn(mockSshOutput);

            Map<String, Object> response = metricsController.getDockerEnv("quan_ly_server", "/home/kirito/quan_ly_server");

            assertNotNull(response, "Response must not be null");
            assertEquals("success", String.valueOf(response.get("status")).toLowerCase(), "Status must be success");
            assertEquals("quan_ly_server", response.get("project"));
            assertEquals("/home/kirito/quan_ly_server/.env", response.get("filePath"));
            assertEquals(true, response.get("hasBackup"), "hasBackup must be true when backup exists");
            assertEquals(rawEnvContent, response.get("content"), "Content must match decoded UTF-8 string");

            verify(sshService, times(1)).executeCommand(anyString());
        }

        @Test
        @DisplayName("2. Read .env success with default workingDir: Defaults to /home/kirito/<project>")
        void testDockerEnv_Get_DefaultWorkingDir_Success() {
            String rawEnv = "NODE_ENV=production\n";
            String b64 = Base64.getEncoder().encodeToString(rawEnv.getBytes(StandardCharsets.UTF_8));
            String mockOutput = b64 + "\n===ENV_SEP===\n0\n";

            when(sshService.executeCommand(argThat(cmd -> 
                cmd != null && cmd.contains("/home/kirito/my_app/.env")
            ))).thenReturn(mockOutput);

            Map<String, Object> response = metricsController.getDockerEnv("my_app", null);

            assertNotNull(response);
            assertEquals("success", String.valueOf(response.get("status")).toLowerCase());
            assertEquals("my_app", response.get("project"));
            assertEquals("/home/kirito/my_app/.env", response.get("filePath"));
            assertEquals(rawEnv, response.get("content"));
            assertEquals(false, response.get("hasBackup"), "hasBackup must be false when .env.bak does not exist");
        }

        @Test
        @DisplayName("3. Path traversal attempts rejected without invoking SSH")
        void testDockerEnv_Get_PathTraversal_Rejected() {
            List<String[]> maliciousVectors = List.of(
                new String[]{"../../etc", null},
                new String[]{"quan_ly_server/..", null},
                new String[]{"quan_ly_server", "/etc"},
                new String[]{"quan_ly_server", "/home/kirito/../../etc"},
                new String[]{"quan_ly_server", "C:/Windows"},
                new String[]{"quan_ly_server", "C:\\Windows\\win.ini"},
                new String[]{"quan_ly_server", "/var/log"},
                new String[]{"quan_ly_server", "/home/kirito/%2e%2e/etc"},
                new String[]{"quan_ly_server", "/home/kirito_other/project"}
            );

            for (String[] vector : maliciousVectors) {
                String project = vector[0];
                String workingDir = vector[1];

                Map<String, Object> response = metricsController.getDockerEnv(project, workingDir);

                assertNotNull(response, "Response must not be null for vector: " + project + ", " + workingDir);
                assertEquals("error", String.valueOf(response.get("status")).toLowerCase(),
                    "Status must be error for path traversal attempt: " + project + " | " + workingDir);
                assertNotNull(response.get("message"), "Error message must be present");
            }

            verify(sshService, never()).executeCommand(anyString());
        }

        @Test
        @DisplayName("4. Invalid project names rejected: Null, empty, special characters")
        void testDockerEnv_Get_InvalidProject_Rejected() {
            List<String> invalidProjects = List.of(
                "quan;rm -rf /",
                "proj$(whoami)",
                "proj|pipe",
                "proj&background",
                ".",
                "",
                "   "
            );

            for (String invalidProject : invalidProjects) {
                Map<String, Object> response = metricsController.getDockerEnv(invalidProject, null);
                assertNotNull(response);
                assertEquals("error", String.valueOf(response.get("status")).toLowerCase());
                assertNotNull(response.get("message"));
            }

            Map<String, Object> nullProjRes = metricsController.getDockerEnv(null, null);
            assertEquals("error", nullProjRes.get("status"));

            verify(sshService, never()).executeCommand(anyString());
        }

        @Test
        @DisplayName("5. File .env not found on server: SshService returns ENV_NOT_FOUND")
        void testDockerEnv_Get_FileNotFound_ReturnsError() {
            when(sshService.executeCommand(anyString())).thenReturn("ENV_NOT_FOUND\n");

            Map<String, Object> response = metricsController.getDockerEnv("unknown_project", "/home/kirito/unknown_project");

            assertNotNull(response);
            assertEquals("error", String.valueOf(response.get("status")).toLowerCase());
            assertTrue(String.valueOf(response.get("message")).toLowerCase().contains("not exist")
                    || String.valueOf(response.get("message")).toLowerCase().contains("not found"));
            assertEquals(false, response.get("hasBackup"));
        }

        @Test
        @DisplayName("6. SSH failure or timeout: Returns error response")
        void testDockerEnv_Get_SshFailure_ReturnsError() {
            when(sshService.executeCommand(anyString())).thenReturn("Lỗi SSH (sau 3 lần thử): Connection timed out\n");

            Map<String, Object> response = metricsController.getDockerEnv("quan_ly_server", "/home/kirito/quan_ly_server");

            assertNotNull(response);
            assertEquals("error", String.valueOf(response.get("status")).toLowerCase());
            assertTrue(String.valueOf(response.get("message")).contains("Lỗi SSH"));
        }
    }

    @Nested
    @DisplayName("Tests for POST /api/metrics/docker/env (updateDockerEnv & saveDockerEnv)")
    class UpdateDockerEnvTests {

        @Test
        @DisplayName("1. Save .env with backup and restart: Atomic write, base64 payload, backup snapshot & detached restart")
        void testDockerEnv_Post_Success_WithBackupAndRestart() {
            String newEnvContent = "DB_HOST=172.18.0.1\nDB_PORT=5432\nJWT_SECRET=reloaded_secret\nCOMMENT=Bảo mật\n";
            String expectedB64 = Base64.getEncoder().encodeToString(newEnvContent.getBytes(StandardCharsets.UTF_8));

            Map<String, Object> requestBody = new HashMap<>();
            requestBody.put("project", "quan_ly_server");
            requestBody.put("workingDir", "/home/kirito/quan_ly_server");
            requestBody.put("content", newEnvContent);
            requestBody.put("restartProject", true);

            when(sshService.executeCommand(anyString()))
                .thenReturn("BACKUP:/home/kirito/quan_ly_server/.env.bak.20260928_220000\nWRITE_SUCCESS\n");

            Map<String, Object> response = metricsController.updateDockerEnv(requestBody);

            assertNotNull(response);
            assertEquals("success", String.valueOf(response.get("status")).toLowerCase());
            assertEquals(true, response.get("restarted"));
            assertEquals("/home/kirito/quan_ly_server/.env.bak.20260928_220000", response.get("backupPath"));
            assertEquals(".env file updated successfully", response.get("message"));

            ArgumentCaptor<String> cmdCaptor = ArgumentCaptor.forClass(String.class);
            verify(sshService, times(1)).executeCommand(cmdCaptor.capture());
            String executedCmd = cmdCaptor.getValue();

            // 1. Safe Atomic Write via Base64 decode to .env.tmp and atomic move
            assertTrue(executedCmd.contains("base64 -d") || executedCmd.contains("base64 --decode"),
                "Command must use base64 decoding to write file safely");
            assertTrue(executedCmd.contains(expectedB64), "Command must contain base64 encoded content");
            assertTrue(executedCmd.contains(".env.tmp"), "Command must write to .env.tmp first");
            assertTrue(executedCmd.contains("mv -f"), "Command must atomically move .env.tmp to .env");

            // 2. Auto-Backup snapshots
            assertTrue(executedCmd.contains("cp -f") || executedCmd.contains(".bak"),
                "Command must create .env.bak backup snapshot");

            // 3. Detached non-blocking restart
            assertTrue(executedCmd.contains("docker compose up -d"),
                "Command must trigger docker compose up -d when restartProject is true");
            assertTrue(executedCmd.contains("&"), "Restart command must be detached with & to avoid blocking HTTP thread");
        }

        @Test
        @DisplayName("2. Save .env without restart: Writes .env without invoking docker compose")
        void testDockerEnv_Post_Success_WithoutRestart() {
            Map<String, Object> requestBody = Map.of(
                "project", "quan_ly_server",
                "workingDir", "/home/kirito/quan_ly_server",
                "content", "KEY=VALUE",
                "restartProject", false
            );

            when(sshService.executeCommand(anyString())).thenReturn("WRITE_SUCCESS\n");

            Map<String, Object> response = metricsController.updateDockerEnv(requestBody);

            assertNotNull(response);
            assertEquals("success", String.valueOf(response.get("status")).toLowerCase());
            assertEquals(false, response.get("restarted"));
            assertNotNull(response.get("backupPath"));

            ArgumentCaptor<String> captor = ArgumentCaptor.forClass(String.class);
            verify(sshService).executeCommand(captor.capture());
            String cmd = captor.getValue();
            assertFalse(cmd.contains("docker compose up"), "Command must NOT restart project when restartProject is false");
        }

        @Test
        @DisplayName("3. Invalid project name rejected without invoking SSH")
        void testDockerEnv_Post_InvalidProject_Rejected() {
            List<String> invalidProjects = List.of(
                "quan_ly_server; rm -rf /",
                "proj$(whoami)",
                "proj`id`",
                "../../etc",
                "project with space",
                "proj|pipe",
                "proj&background",
                "",
                " "
            );

            for (String invalidProject : invalidProjects) {
                Map<String, Object> requestBody = new HashMap<>();
                requestBody.put("project", invalidProject);
                requestBody.put("workingDir", "/home/kirito/valid_dir");
                requestBody.put("content", "FOO=BAR");

                Map<String, Object> response = metricsController.updateDockerEnv(requestBody);

                assertNotNull(response);
                assertEquals("error", String.valueOf(response.get("status")).toLowerCase(),
                    "Status must be error for invalid project: " + invalidProject);
            }

            verify(sshService, never()).executeCommand(anyString());
        }

        @Test
        @DisplayName("4. Path traversal in workingDir rejected without invoking SSH")
        void testDockerEnv_Post_InvalidWorkingDir_Rejected() {
            List<String> invalidDirs = List.of(
                "/etc",
                "/root",
                "/home/kirito/../../var",
                "C:/Windows/System32",
                "C:\\Windows",
                "/var/run/docker",
                "/home/kirito/%2e%2e/etc"
            );

            for (String invalidDir : invalidDirs) {
                Map<String, Object> requestBody = Map.of(
                    "project", "quan_ly_server",
                    "workingDir", invalidDir,
                    "content", "FOO=BAR"
                );

                Map<String, Object> response = metricsController.updateDockerEnv(requestBody);

                assertNotNull(response);
                assertEquals("error", String.valueOf(response.get("status")).toLowerCase());
            }

            verify(sshService, never()).executeCommand(anyString());
        }

        @Test
        @DisplayName("5. Content payload exceeding 1MB limit rejected")
        void testDockerEnv_Post_PayloadTooLarge() {
            String largeContent = "A".repeat(1_000_001);
            Map<String, Object> requestBody = Map.of(
                "project", "quan_ly_server",
                "content", largeContent
            );

            Map<String, Object> response = metricsController.updateDockerEnv(requestBody);
            assertNotNull(response);
            assertEquals("error", String.valueOf(response.get("status")).toLowerCase());
            assertTrue(response.get("message").toString().contains("Payload too large"));
            verify(sshService, never()).executeCommand(anyString());
        }

        @Test
        @DisplayName("6. Write failure on host returns error and does not restart")
        void testDockerEnv_Post_WriteFailure_ReturnsError() {
            Map<String, Object> requestBody = Map.of(
                "project", "quan_ly_server",
                "workingDir", "/home/kirito/quan_ly_server",
                "content", "DATA=1\n",
                "restartProject", true
            );

            when(sshService.executeCommand(anyString())).thenReturn("WRITE_FAILED\n");

            Map<String, Object> response = metricsController.updateDockerEnv(requestBody);

            assertNotNull(response);
            assertEquals("error", String.valueOf(response.get("status")).toLowerCase());
            assertTrue(response.get("message").toString().contains("Failed to write .env file"));
        }

        @Test
        @DisplayName("7. Target directory not found on host returns error")
        void testDockerEnv_Post_DirectoryNotFound_ReturnsError() {
            Map<String, Object> requestBody = Map.of(
                "project", "quan_ly_server",
                "workingDir", "/home/kirito/non_existent_dir",
                "content", "DATA=1\n"
            );

            when(sshService.executeCommand(anyString())).thenReturn("DIR_NOT_FOUND\n");

            Map<String, Object> response = metricsController.updateDockerEnv(requestBody);

            assertNotNull(response);
            assertEquals("error", String.valueOf(response.get("status")).toLowerCase());
            assertTrue(response.get("message").toString().contains("Target directory does not exist"));
        }

        @Test
        @DisplayName("8. saveDockerEnv method alias works identically to updateDockerEnv")
        void testDockerEnv_Post_SaveDockerEnvAlias_Works() {
            when(sshService.executeCommand(anyString())).thenReturn("WRITE_SUCCESS\n");

            Map<String, Object> body = Map.of(
                "project", "quan_ly_server",
                "content", "FOO=BAR"
            );

            Map<String, Object> response = metricsController.saveDockerEnv(body);

            assertNotNull(response);
            assertEquals("success", response.get("status"));
        }

        @Test
        @DisplayName("9. Null request body returns error")
        void testDockerEnv_Post_NullBody_ReturnsError() {
            Map<String, Object> response = metricsController.updateDockerEnv(null);
            assertNotNull(response);
            assertEquals("error", response.get("status"));
            verify(sshService, never()).executeCommand(anyString());
        }
    }

    @Nested
    @DisplayName("Tests for POST /api/metrics/docker/project/control (controlDockerProject)")
    class ControlDockerProjectTests {

        @Test
        @DisplayName("1. Action 'restart' executes 'docker compose restart' with 2>&1 stderr redirection")
        void testDockerProjectControl_Success() {
            String mockOutput = "[+] Restarting 6/6\n ✔ Container dashboard_frontend Restarted\n ✔ Container dashboard_metrics_service Restarted\n";
            when(sshService.executeCommand(argThat(cmd -> 
                cmd != null && cmd.contains("cd /home/kirito/quan_ly_server") && cmd.contains("docker compose restart") && cmd.contains("2>&1")
            ))).thenReturn(mockOutput);

            Map<String, Object> response = metricsController.controlDockerProject("quan_ly_server", "restart", "/home/kirito/quan_ly_server");

            assertNotNull(response);
            assertEquals("success", String.valueOf(response.get("status")).toLowerCase());
            assertEquals("restart", response.get("action"));
            assertEquals("quan_ly_server", response.get("project"));
            assertTrue(String.valueOf(response.get("output")).contains("Restarted"));

            verify(sshService, times(1)).executeCommand(anyString());
        }

        @Test
        @DisplayName("2. Whitelisted actions: start, stop, and up (mapped to 'up -d')")
        void testDockerProjectControl_WhitelistedActions_Success() {
            List<String[]> actionsToTest = List.of(
                new String[]{"start", "docker compose start"},
                new String[]{"stop", "docker compose stop"},
                new String[]{"up", "docker compose up -d"}
            );

            for (String[] pair : actionsToTest) {
                String action = pair[0];
                String expectedComposeCmd = pair[1];

                when(sshService.executeCommand(argThat(cmd -> cmd != null && cmd.contains(expectedComposeCmd))))
                    .thenReturn("[+] Action " + action + " executed successfully\n");

                Map<String, Object> response = metricsController.controlDockerProject("quan_ly_server", action, "/home/kirito/quan_ly_server");

                assertNotNull(response);
                assertEquals("success", String.valueOf(response.get("status")).toLowerCase());
                assertEquals(action, response.get("action"));
            }
        }

        @Test
        @DisplayName("3. Request body JSON payload supported seamlessly")
        void testDockerProjectControl_RequestBodyJson_Supported() {
            String mockOutput = "[+] Stopping 6/6\n ✔ Container dashboard_db Stopped";
            when(sshService.executeCommand(argThat(cmd -> cmd != null && cmd.contains("docker compose stop"))))
                .thenReturn(mockOutput);

            Map<String, Object> body = Map.of(
                "project", "quan_ly_server",
                "action", "stop",
                "workingDir", "/home/kirito/quan_ly_server"
            );

            Map<String, Object> response = metricsController.controlDockerProject(body, null, null, null);

            assertNotNull(response);
            assertEquals("success", response.get("status"));
            assertEquals("stop", response.get("action"));
            assertEquals("quan_ly_server", response.get("project"));
        }

        @Test
        @DisplayName("4. Invalid actions rejected by whitelist: destroy, kill, command injection")
        void testDockerProjectControl_InvalidAction_Rejected() {
            List<String> invalidActions = List.of(
                "destroy",
                "restart; rm -rf /",
                "up && cat /etc/shadow",
                "$(reboot)",
                "`whoami`",
                "kill",
                "exec",
                "down",
                "",
                " "
            );

            for (String invalidAction : invalidActions) {
                Map<String, Object> response = metricsController.controlDockerProject("quan_ly_server", invalidAction, "/home/kirito/quan_ly_server");

                assertNotNull(response);
                assertEquals("error", String.valueOf(response.get("status")).toLowerCase(),
                    "Status must be error for illegal action: " + invalidAction);
                assertNotNull(response.get("message"), "Error message must be present for illegal action");
            }

            verify(sshService, never()).executeCommand(anyString());
        }

        @Test
        @DisplayName("5. Invalid project name rejected without invoking SSH")
        void testDockerProjectControl_InvalidProjectName_Rejected() {
            List<String> invalidProjects = List.of("../../etc", "quan;rm -rf /", "", " ");

            for (String proj : invalidProjects) {
                Map<String, Object> response = metricsController.controlDockerProject(proj, "restart", null);
                assertNotNull(response);
                assertEquals("error", response.get("status"));
            }

            verify(sshService, never()).executeCommand(anyString());
        }

        @Test
        @DisplayName("6. WorkingDir traversal rejected without invoking SSH")
        void testDockerProjectControl_WorkingDirTraversal_Rejected() {
            Map<String, Object> response = metricsController.controlDockerProject("quan_ly_server", "restart", "/home/kirito/../../etc");

            assertNotNull(response);
            assertEquals("error", String.valueOf(response.get("status")).toLowerCase());
            assertTrue(response.get("message").toString().contains("working directory")
                    || response.get("message").toString().contains("traversal"));
            verify(sshService, never()).executeCommand(anyString());
        }

        @Test
        @DisplayName("7. Working directory does not exist on disk: Returns clear error")
        void testDockerProjectControl_DirectoryNotFoundOnDisk_ReturnsError() {
            when(sshService.executeCommand(anyString()))
                .thenReturn("bash: line 1: cd: /home/kirito/missing_dir: No such file or directory\n");

            Map<String, Object> response = metricsController.controlDockerProject(
                "missing_dir", "restart", "/home/kirito/missing_dir"
            );

            assertNotNull(response);
            assertEquals("error", response.get("status"));
            assertTrue(response.get("message").toString().contains("Working directory does not exist on disk"));
        }

        @Test
        @DisplayName("8. Missing docker-compose.yml configuration file: Returns clear error")
        void testDockerProjectControl_ComposeFileNotFound_ReturnsError() {
            when(sshService.executeCommand(anyString()))
                .thenReturn("no configuration file provided: not found\n");

            Map<String, Object> response = metricsController.controlDockerProject(
                "no_compose_proj", "restart", "/home/kirito/no_compose_proj"
            );

            assertNotNull(response);
            assertEquals("error", response.get("status"));
            assertTrue(response.get("message").toString().contains("Compose configuration file (docker-compose.yml) not found"));
        }

        @Test
        @DisplayName("9. Docker daemon runtime failure: Returns error message")
        void testDockerProjectControl_ComposeActionFailure_ReturnsError() {
            when(sshService.executeCommand(anyString()))
                .thenReturn("Error response from daemon: port is already allocated\n");

            Map<String, Object> response = metricsController.controlDockerProject(
                "quan_ly_server", "start", null
            );

            assertNotNull(response);
            assertEquals("error", response.get("status"));
            assertTrue(response.get("message").toString().contains("Error response from daemon"));
        }

        @Test
        @DisplayName("10. SSH failure or timeout: Returns error response")
        void testDockerProjectControl_SshFailureOrTimeout_ReturnsError() {
            when(sshService.executeCommand(anyString()))
                .thenReturn("Lỗi SSH (sau 3 lần thử): Connection timed out\n");

            Map<String, Object> response = metricsController.controlDockerProject(
                "quan_ly_server", "restart", null
            );

            assertNotNull(response);
            assertEquals("error", response.get("status"));
            assertTrue(response.get("message").toString().contains("Lỗi SSH"));
        }
    }
}
