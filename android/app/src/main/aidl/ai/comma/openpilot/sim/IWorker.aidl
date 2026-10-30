package ai.comma.openpilot.sim;

interface IWorker {
    void start(String session, String daemon);
    void startConfigured(String session, String daemon, String environment);
    String status();
    String checkRuntime(String session);
    String probeIpc(String session, boolean publisher);
    String probeModel(String session);
    String probeSchema(String session);
    void stop();
}
