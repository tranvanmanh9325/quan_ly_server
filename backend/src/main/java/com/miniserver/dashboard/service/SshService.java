package com.miniserver.dashboard.service;

import com.jcraft.jsch.ChannelExec;
import com.jcraft.jsch.JSch;
import com.jcraft.jsch.Session;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
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

    // Session duy nhất được tái sử dụng cho toàn bộ vòng đời ứng dụng
    private Session sharedSession;

    /**
     * Trả về session hiện có nếu còn kết nối, ngược lại tạo mới.
     * synchronized đảm bảo an toàn khi 8 request đồng thời gọi vào.
     */
    private synchronized Session getOrCreateSession() throws Exception {
        if (sharedSession != null && sharedSession.isConnected()) {
            return sharedSession;
        }

        log.info("SSH: Đang tạo kết nối mới tới {}@{}:{}", user, host, port);

        JSch jsch = new JSch();
        Session session = jsch.getSession(user, host, port);
        session.setPassword(password);

        Properties config = new Properties();
        config.put("StrictHostKeyChecking", "no");
        session.setConfig(config);
        // Giữ kết nối sống, gửi keepalive mỗi 30s để Ngrok không cắt tunnel
        session.setServerAliveInterval(30_000);
        session.setServerAliveCountMax(3);
        session.connect(15_000);

        sharedSession = session;
        log.info("SSH: Kết nối thành công.");
        return sharedSession;
    }

    public String executeCommand(String command) {
        // Exponential backoff: 3 lần thử với delay tăng dần trước khi bỏ cuộc
        int[] retryDelaysMs = {250, 500, 1000};
        Exception lastException = null;

        for (int attempt = 0; attempt <= retryDelaysMs.length; attempt++) {
            ChannelExec channel = null;
            try {
                Session session = getOrCreateSession();
                channel = (ChannelExec) session.openChannel("exec");
                channel.setCommand(command);
                channel.setInputStream(null);
                channel.setErrStream(System.err);

                // BufferedReader xử lý UTF-8 đúng hơn, tránh lỗi cắt byte giữa chừng
                BufferedReader reader = new BufferedReader(new InputStreamReader(channel.getInputStream()));
                channel.connect(10_000);

                StringBuilder outputBuffer = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    outputBuffer.append(line).append('\n');
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

        log.error("SSH thất bại sau {} lần thử: {}", retryDelaysMs.length + 1, lastException != null ? lastException.getMessage() : "unknown");
        return "ERROR: " + (lastException != null ? lastException.getMessage() : "unknown");
    }

    @PreDestroy
    public synchronized void cleanup() {
        if (sharedSession != null && sharedSession.isConnected()) {
            log.info("SSH: Đóng session khi Spring shutdown.");
            sharedSession.disconnect();
        }
    }
}
