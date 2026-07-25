package com.miniserver.dashboard.controller;

import com.miniserver.dashboard.service.SshService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class FileManagerControllerTest {

    @Mock
    private SshService sshService;

    @InjectMocks
    private FileManagerController fileManagerController;

    @Test
    @DisplayName("listDirectory - should block access to restricted sensitive paths")
    void testListDirectory_RestrictedPath() {
        Map<String, Object> res = fileManagerController.listDirectory("/etc/shadow");

        assertEquals("error", res.get("status"));
        assertTrue(res.get("message").toString().contains("Access denied"));
        verify(sshService, never()).executeCommand(anyString());
    }

    @Test
    @DisplayName("listDirectory - should parse ls -la output correctly")
    void testListDirectory_Success() {
        String mockLs = "total 24\n" +
                        "drwxr-xr-x 2 root root 4096 2026-07-24 12:00 .\n" +
                        "-rw-r--r-- 1 root root 1024 2026-07-24 12:00 config.json";
        when(sshService.executeCommand(anyString())).thenReturn(mockLs);

        Map<String, Object> res = fileManagerController.listDirectory("/var/log");

        assertEquals("success", res.get("status"));
        @SuppressWarnings("unchecked")
        List<Map<String, String>> files = (List<Map<String, String>>) res.get("files");
        assertEquals(2, files.size());
        assertEquals("config.json", files.get(1).get("name"));
    }

    @Test
    @DisplayName("readFile - should block sensitive files")
    void testReadFile_Restricted() {
        Map<String, String> res = fileManagerController.readFile("/etc/shadow", 100);

        assertEquals("error", res.get("status"));
        assertTrue(res.get("data").contains("Access denied"));
    }

    @Test
    @DisplayName("readFile - should read allowed file content safely")
    void testReadFile_Success() {
        when(sshService.executeCommand(anyString())).thenReturn("server { listen 80; }");

        Map<String, String> res = fileManagerController.readFile("/etc/nginx/nginx.conf", 50);

        assertEquals("success", res.get("status"));
        assertTrue(res.get("data").contains("listen 80"));
    }
}
