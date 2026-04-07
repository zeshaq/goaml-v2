# OpenShift Service Mesh mTLS with HashiCorp Vault Architecture

This diagram illustrates the infrastructure and flow for implementing mutual TLS (mTLS) in OpenShift Service Mesh, backed by HashiCorp Vault as the Certificate Authority (CA).

```mermaid
graph TD
    %% Define components
    subgraph "HashiCorp Vault Infrastructure"
        VaultCA["Vault PKI Secret Engine<br/>(Root & Intermediate CA)"]
        VaultAuth["Vault Kubernetes<br/>Auth Method"]
    end

    subgraph "OpenShift Cluster"
        subgraph "Control Plane (istio-system)"
            CertManager["Cert-Manager<br/>(cert-manager.io)"]
            IstioCSR["cert-manager<br/>istio-csr"]
            Istiod["Istiod<br/>(Service Mesh Control Plane)"]
        end

        subgraph "Application Namespace"
            subgraph "Pod: Service A"
                AppA["Application Container A"]
                EnvoyA["Envoy Proxy Container"]
            end
            
            subgraph "Pod: Service B"
                AppB["Application Container B"]
                EnvoyB["Envoy Proxy Container"]
            end
        end
    end

    %% Flow: Bootstrapping CA Integration
    CertManager -- "1. Auth via ServiceAccount" --> VaultAuth
    VaultAuth -- "2. Validates & Returns Token" --> CertManager
    CertManager -- "3. Requests Intermediate CA" --> VaultCA
    VaultCA -- "4. Issues Intermediate CA" --> CertManager
    
    %% Flow: Control Plane integration
    IstioCSR -- "5. Watches & validates requests" --> CertManager
    IstioCSR -- "6. Provides CA & Trust Bundle" --> Istiod

    %% Flow: Workload Certificate Provisioning
    Istiod -- "7. Sends Workload Certs (SDS)" --> EnvoyA
    Istiod -- "8. Sends Workload Certs (SDS)" --> EnvoyB

    %% Flow: Application Communication
    AppA -. "9. Unencrypted Local" .-> EnvoyA
    EnvoyA <== "10. Encrypted mTLS Traffic" ===> EnvoyB
    EnvoyB -. "11. Unencrypted Local" .-> AppB

    %% Styling
    classDef vault fill:#27272a,stroke:#c084fc,stroke-width:2px,color:#fff;
    classDef controlplane fill:#18181b,stroke:#38bdf8,stroke-width:2px,color:#fff;
    classDef proxy fill:#18181b,stroke:#f59e0b,stroke-width:2px,color:#fff;
    classDef app fill:#09090b,stroke:#10b981,stroke-width:2px,color:#fff;

    class VaultCA,VaultAuth vault;
    class CertManager,IstioCSR,Istiod controlplane;
    class EnvoyA,EnvoyB proxy;
    class AppA,AppB app;
```

### Key Components & Flow Details:

1. **HashiCorp Vault**: Acts as the external Root CA and generates the Intermediate CA used by the mesh.
2. **Cert-Manager & Istio-CSR**: `cert-manager` successfully authenticates with Vault (via OpenShift Kubernetes Auth Method). `istio-csr` operates as an agent that proxies Istio's certificate signing requests to `cert-manager`—preventing Istiod from acting as a CA itself.
3. **Istiod**: The control plane component delegates the CA responsibility and focuses purely on pushing the configuration and signed certificates down to the workloads.
4. **Envoy Proxies**: Inside every pod, Envoy requests a certificate via the Secret Discovery Service (SDS) API from Istiod. 
5. **mTLS**: Application containers talk unencrypted locally to their sidecar Envoy over `localhost`, but whenever Envoy sends traffic across the network to another service, it uses the Vault-backed certificates to establish an authenticated, encrypted mTLS tunnel.
