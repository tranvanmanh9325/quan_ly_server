package com.miniserver.file.service;

import com.jcraft.jsch.ChannelExec;
import com.jcraft.jsch.JSch;
import com.jcraft.jsch.Session;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.InputStreamReader;
import java.util.Properties;
@Service
public class SshService {

    private static final Logger log = LoggerFactory.getLogger(SshService.class);

    @Value("${ssh.host}")
    private String host;

    @Value("${ssh.port}")
    private int port;

    @Value("${ssh.user}")
    private String user;

    @Value("${ssh.password}")
    private String password;

    @Value("${ssh.strict-host-key-checking:no}")
    private String strictHostKeyChecking;

    // Fallback host/port (e.g. ngrok) used when primary is unreachable (different network)
    @Value("${ssh.fallback-host:}")
    private String fallbackHost;

    @Value("${ssh.fallback-port:22}")
    private int fallbackPort;

    // Session duy nhất được tái sử dụng cho toàn bộ vòng đời ứng dụng
    private Session sharedSession;

    /**
     * Trả về session hiện có nếu còn kết nối, ngược lại tạo mới.
     * synchronized đảm bảo an toàn khi nhiều request đồng thời gọi vào.
     */
    private synchronized Session getOrCreateSession() throws Exception {
        if (sharedSession != null && sharedSession.isConnected()) {
            return sharedSession;
        }

        // Try primary host (LAN) first
        try {
            sharedSession = connect(host, port);
            log.info("SSH: Kết nối thành công qua LAN ({}:{}).", host, port);
            return sharedSession;
        } catch (Exception primaryEx) {
            log.warn("SSH: LAN không thể kết nối ({}:{}): {}", host, port, primaryEx.getMessage());

            // Fallback to ngrok/remote address if configured
            if (fallbackHost != null && !fallbackHost.isBlank()) {
                log.info("SSH: Thử fallback qua {} ({}:{})...", 
                         fallbackHost.contains("ngrok") ? "ngrok" : "remote", fallbackHost, fallbackPort);
                sharedSession = connect(fallbackHost, fallbackPort);
                log.info("SSH: Kết nối thành công qua fallback ({}:{}).", fallbackHost, fallbackPort);
                return sharedSession;
            }

            throw primaryEx; // No fallback configured, propagate original error
        }
    }

    /** Creates and connects a new JSch session to the given host:port. */
    private Session connect(String targetHost, int targetPort) throws Exception {
        log.info("SSH: Đang kết nối tới {}@{}:{}", user, targetHost, targetPort);
        JSch jsch = new JSch();
        Session session = jsch.getSession(user, targetHost, targetPort);
        session.setPassword(password.getBytes(java.nio.charset.StandardCharsets.UTF_8));

        Properties config = new Properties();
        config.put("StrictHostKeyChecking", strictHostKeyChecking);
        session.setConfig(config);
        // Keepalive prevents ngrok from dropping idle tunnels
        session.setServerAliveInterval(30_000);
        session.setServerAliveCountMax(3);
        session.connect(8_000); // 8s timeout — fast enough to detect unreachable LAN
        return session;
    }

    /**
     * Thực thi lệnh với quyền sudo (dùng password SSH để tự động nhập vào sudo -S qua stdin).
     */
    public String executeSudoCommand(String command) {
        if ("root".equalsIgnoreCase(user)) {
            return executeCommand(command);
        }
        if (password != null && !password.isBlank()) {
            String sudoCmd = "sudo -S -p '' " + command;
            return executeCommand(sudoCmd, password + "\n");
        }
        return executeCommand("sudo -n " + command + " 2>/dev/null || " + command);
    }

    public String executeCommand(String command) {
        return executeCommand(command, null);
    }

    public String executeCommand(String command, String stdinInput) {
        // Exponential backoff: 3 lần thử với delay tăng dần trước khi bỏ cuộc
        int[] retryDelaysMs = {250, 500, 1000};
        Exception lastException = null;

        for (int attempt = 0; attempt <= retryDelaysMs.length; attempt++) {
            ChannelExec channel = null;
            try {
                Session session = getOrCreateSession();
                channel = (ChannelExec) session.openChannel("exec");
                channel.setCommand(command);

                if (stdinInput != null) {
                    channel.setInputStream(new java.io.ByteArrayInputStream(stdinInput.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
                } else {
                    channel.setInputStream(null);
                }

                // Capture stderr qua SLF4J thay vì System.err để không bypass Logback
                // và đảm bảo log container hoạt động đúng trong môi trường Docker
                ByteArrayOutputStream errBuffer = new ByteArrayOutputStream();
                channel.setErrStream(errBuffer);

                // BufferedReader xử lý UTF-8 đúng hơn, tránh lỗi cắt byte giữa chừng
                BufferedReader reader = new BufferedReader(new InputStreamReader(channel.getInputStream()));
                channel.connect(10_000);

                StringBuilder outputBuffer = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    outputBuffer.append(line).append('\n');
                }

                // Log stderr qua SLF4J nếu lệnh có output lỗi
                String errOutput = errBuffer.toString().trim();
                if (!errOutput.isEmpty()) {
                    log.warn("SSH stderr [{}]: {}", command.substring(0, Math.min(command.length(), 50)), errOutput);
                }

                return outputBuffer.toString();
            } catch (Exception e) {
                lastException = e;
                // Huỷ session lỗi để lần thử tiếp tạo lại
                synchronized (this) {
                    if (sharedSession != null) {
                        sharedSession.disconnect();
                        sharedSession = null;
                    }
                }
                if (attempt < retryDelaysMs.length) {
                    log.warn("SSH lỗi (lần {}), thử lại sau {}ms: {}", attempt + 1, retryDelaysMs[attempt], e.getMessage());
                    try { Thread.sleep(retryDelaysMs[attempt]); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); break; }
                }
            } finally {
                if (channel != null && channel.isConnected()) {
                    channel.disconnect();
                }
            }
        }

        log.error("SSH command execution failed after retries: {}", lastException != null ? lastException.getMessage() : "Unknown");
        return "Lỗi SSH (sau " + retryDelaysMs.length + " lần thử): " +
               (lastException != null ? lastException.getMessage() : "Unknown");
    }

    @PreDestroy
    public synchronized void cleanup() {
        if (sharedSession != null && sharedSession.isConnected()) {
            log.info("SSH: Đóng session khi Spring shutdown.");
            sharedSession.disconnect();
        }
    }
}