# Helm Chart 동적 버전 관리 가이드

## 1. 문제: `Chart.yaml` 병합 충돌

현재 워크플로에서는 `develop`, `staging`, `main` 브랜치에서 `Chart.yaml` 파일의 `version` 또는 `appVersion` 필드를 각 환경에 맞게 직접 수정하고 커밋하고 있습니다. 이로 인해 브랜치 병합 시 `Chart.yaml` 파일에서 빈번하게 충돌이 발생하고 있습니다.

Git은 파일 내용이 같더라도 커밋 히스토리가 다르면 충돌로 인식하며, 특히 `squash merge`는 히스토리를 압축하기 때문에 이러한 충돌 해결을 더욱 복잡하게 만듭니다.

## 2. 해결책: 동적 Helm 버전 관리

`Chart.yaml` 병합 충돌을 완전히 해결하고 배포 프로세스를 효율화하기 위해 **Helm의 동적 버전 관리** 전략을 도입합니다. 핵심 원칙은 다음과 같습니다.

**`Chart.yaml` 파일 자체를 Git 브랜치에서 환경별로 수정하지 않습니다.**

대신, CI/CD 파이프라인이 배포 시점에 필요한 버전 정보를 동적으로 주입하도록 워크플로를 변경합니다.

### 2.1. `Chart.yaml` 관리 (범용 값 유지)

`Chart.yaml` 파일은 Chart 자체의 버전(`version`)과 애플리케이션의 기본 버전(`appVersion`)을 정의합니다. 이 파일은 **환경별로 수정되지 않아야 합니다.** `appVersion`은 CI/CD에서 동적으로 주입될 것이므로, 플레이스홀더 값을 둡니다.

```yaml
# Chart.yaml
apiVersion: v2
name: webhook-service
description: A Helm chart for the Webhook Service
type: application
version: 0.1.0 # Chart 자체의 버전. Chart 구조 변경 시에만 업데이트.
appVersion: "0.0.0-placeholder" # CI/CD에서 동적으로 주입될 값의 플레이스홀더
```

### 2.2. `values.yaml` 관리 (환경별 설정 오버라이드)

환경별로 다른 설정(예: 데이터베이스 URL, API 키 등)은 `values.yaml`에 정의하고, 배포 시점에 `--values` 플래그를 사용하여 환경별 `values` 파일을 적용합니다. Docker 이미지 태그도 `values.yaml`을 통해 관리할 수 있습니다.

```yaml
# values.yaml (기본값 예시)
image:
  repository: ghcr.io/grinvi04/webhook-service # 또는 ECR 경로
  tag: latest # 기본 이미지 태그

# values-staging.yaml (staging 환경용 오버라이드 예시)
image:
  tag: rc-${{ github.run_number }} # staging 환경에 배포할 이미지 태그

# values-production.yaml (production 환경용 오버라이드 예시)
image:
  tag: v1.0.0 # production 환경에 배포할 이미지 태그 (또는 커밋 SHA)
```

### 2.3. CI/CD 파이프라인에서 동적 버전 주입

CI/CD 파이프라인이 각 브랜치/이벤트에 따라 Docker 이미지에 적절한 태그를 지정하고, Helm 배포 시점에 이 태그를 동적으로 주입하도록 워크플로를 변경합니다.

**`ci.yml` (예시 - Docker 이미지 빌드 및 푸시 부분):**

```yaml
# ... (생략) ...

      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ghcr.io/${{ github.repository }}:${{ github.sha }}
          # 또는 브랜치별 태그 전략:
          # tags: ghcr.io/${{ github.repository }}:develop-${{ github.sha_short }}
          # tags: ghcr.io/${{ github.repository }}:rc-${{ github.run_number }}
          # tags: ghcr.io/${{ github.repository }}:v1.0.0 # main 브랜치용
          cache-from: type=gha
          cache-to: type=gha,mode=max

# ... (생략) ...

# 배포 잡 (예시 - ECR 및 Helm 배포 포함)
deploy:
  runs-on: ubuntu-latest
  needs: build-and-push # 이미지 빌드 및 푸시가 성공한 후에 실행
  environment: # GitHub Environments를 사용하여 환경별 설정 관리
    name: ${{ github.ref == 'refs/heads/main' && 'Production' || 'Staging' }}
  steps:
    - uses: actions/checkout@v4

    - name: Configure AWS credentials (ECR 사용 시)
      if: ${{ github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/staging' || github.ref == 'refs/heads/main' }}
      uses: aws-actions/configure-aws-credentials@v4
      with:
        aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
        aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
        aws-region: your-aws-region # AWS 리전 설정

    - name: Login to ECR (ECR 사용 시)
      if: ${{ github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/staging' || github.ref == 'refs/heads/main' }}
      run: |
        aws ecr get-login-password --region your-aws-region | docker login --username AWS --password-stdin your-ecr-registry-url

    - name: Deploy Helm Chart
      run: |
        # 브랜치에 따라 동적으로 이미지 태그 결정
        IMAGE_TAG=""
        if [[ "${{ github.ref }}" == "refs/heads/develop" ]]; then
          IMAGE_TAG="develop-${{ github.sha_short }}"
        elif [[ "${{ github.ref }}" == "refs/heads/staging" ]]; then
          IMAGE_TAG="rc-${{ github.run_number }}" # 또는 다른 RC 태그 전략
        elif [[ "${{ github.ref }}" == "refs/heads/main" ]]; then
          IMAGE_TAG="v1.0.0" # 또는 semantic versioning에 따른 실제 버전
        fi

        # Helm Chart가 있는 디렉토리로 이동 (예: ./helm/webhook-service)
        # cd ./helm/webhook-service

        # Helm Chart 배포
        # --set image.tag=${IMAGE_TAG} 를 사용하여 이미지 태그를 동적으로 주입
        # -f values-${{ github.ref_name }}.yaml 을 사용하여 환경별 값 적용 (예: values-develop.yaml, values-staging.yaml, values-main.yaml)
        helm upgrade --install webhook-service-${{ github.ref_name }} .
          --namespace ${{ github.ref_name }}
          --create-namespace
          --set image.tag=${IMAGE_TAG}
          -f values-${{ github.ref_name }}.yaml # 환경별 values 파일 사용
```

## 3. 단계별 구현 가이드

### 3.1. `Chart.yaml` 수정

위의 `Chart.yaml` 예시처럼 `version`과 `appVersion`을 범용적인 값으로 변경하고, 더 이상 브랜치별로 이 파일을 수정하지 않습니다.

### 3.2. CI/CD (`.github/workflows/ci.yml`) 수정

현재 `ci.yml` 파일에 이미지 빌드 및 푸시 로직이 있습니다. 여기에 동적 태그 지정 로직을 추가하고, 별도의 배포 잡(Job)을 생성하여 Helm 배포 로직을 추가합니다. 위의 `ci.yml` 예시를 참고하여 `build-and-push` 잡과 `deploy` 잡을 구성합니다.

*   **`build-and-push` 잡**: `tags` 필드를 `ghcr.io/${{ github.repository }}:${{ github.sha }}`와 같이 커밋 SHA를 기반으로 하는 고유한 태그로 변경합니다. 또는 브랜치별 태그 전략을 구현합니다.
*   **`deploy` 잡**: Helm Chart가 있는 디렉토리로 이동하여 `helm upgrade --install` 명령을 실행하고, `IMAGE_TAG` 변수를 통해 동적으로 이미지 태그를 주입합니다. 환경별 `values` 파일을 사용하도록 설정합니다.

### 3.3. `docker-compose.prod.yml` 업데이트

`docker-compose.prod.yml` 파일은 이미 `ghcr.io/${{ github.repository }}:latest`를 사용하도록 업데이트되어 있습니다. 이제 이 `latest` 태그 대신 CI/CD에서 푸시하는 특정 태그(예: `ghcr.io/${{ github.repository }}:v1.0.0` 또는 `ghcr.io/${{ github.repository }}:${{ github.sha }}`)를 사용하도록 변경해야 합니다. 이는 배포 스크립트에서 동적으로 설정될 수 있습니다.

## 4. 기대 효과

*   **`Chart.yaml` 충돌 완전 제거**: 버전 정보로 인한 Git 병합 충돌이 원천적으로 사라집니다.
*   **배포 프로세스 자동화 및 일관성**: 수동 개입 없이 각 환경에 맞는 정확한 버전이 배포됩니다.
*   **단일 빌드 아티팩트 승격**: 동일한 이미지를 태그만 변경하여 여러 환경에 배포하는 현재의 전략과 완벽하게 부합합니다.
*   **Helm 모범 사례 준수**: Chart의 설계 철학에 더 부합하는 방식으로 버전과 환경별 설정을 관리하게 됩니다.

## 5. 고려 사항

*   **초기 구현 노력**: 기존 워크플로를 변경하고 CI/CD 파이프라인에 Helm 배포 단계를 추가하며 동적 태그 주입 로직을 구현하는 데는 초기 설정 및 학습 노력이 필요합니다.
*   **팀원 교육**: 팀원들이 새로운 버전 관리 및 배포 방식을 이해하고 적용할 수 있도록 충분한 가이드와 교육이 필요합니다.
*   **AWS 자격 증명**: ECR을 사용하는 경우, CI/CD 파이프라인에서 ECR에 접근하기 위한 AWS 자격 증명(Secrets) 설정이 필수적입니다.

이 가이드가 팀원들과의 논의에 도움이 되기를 바랍니다.
