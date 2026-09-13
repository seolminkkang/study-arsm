package study.integration;

import com.rabbitmq.client.*;
import java.nio.charset.StandardCharsets;
import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** 실습 전용 단일 큐. publisher confirm과 consumer ack는 서로 다른 확인이다. */
@Component
class LabQueue {
    private final String host;
    private Connection connection;
    private Channel channel;
    static final String QUEUE="review-points";
    LabQueue(@Value("${lab.broker-host:broker}") String host) { this.host=host; }
    synchronized Channel channel() throws Exception {
        if(channel==null || !channel.isOpen()) {
            close();
            ConnectionFactory f=new ConnectionFactory();
            f.setHost(host); f.setUsername("integration"); f.setPassword("integration-local");
            f.setConnectionTimeout(2000); f.setAutomaticRecoveryEnabled(false);
            connection=f.newConnection(); channel=connection.createChannel();
            channel.queueDeclare(QUEUE,true,false,false,null);
            channel.basicQos(1); channel.confirmSelect();
        }
        return channel;
    }
    synchronized void publish(String id) throws Exception {
        Channel c=channel();
        c.basicPublish("",QUEUE,MessageProperties.PERSISTENT_TEXT_PLAIN,id.getBytes(StandardCharsets.UTF_8));
        c.waitForConfirmsOrDie(2000);
    }
    synchronized GetResponse get() throws Exception { return channel().basicGet(QUEUE,false); }
    synchronized void ack(long tag) throws Exception { channel().basicAck(tag,false); }
    synchronized void retry(long tag) throws Exception { channel().basicNack(tag,false,true); }
    synchronized int pending() throws Exception { return channel().queueDeclarePassive(QUEUE).getMessageCount(); }
    @PreDestroy synchronized void close() {
        try { if(connection!=null) connection.close(); } catch(Exception ignored) { }
        channel=null; connection=null;
    }
}
