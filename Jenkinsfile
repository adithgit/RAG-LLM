pipeline {
    agent any

    triggers {
        githubPush()
    }

    environment {
        PATH = "/usr/local/bin:/opt/homebrew/bin:${env.PATH}"
        DOCKER_REGISTRY = 'adithya952' // Replace with your dockerhub username
        APP_NAME_BACKEND = 'lawracle-backend'
        APP_NAME_FRONTEND = 'lawracle-frontend'
        IMAGE_TAG = "${env.BUILD_ID}"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build & Push Backend Image') {
            steps {
                script {
                    dir('backend') {
                        withCredentials([usernamePassword(credentialsId: 'dockerhub-credentials', passwordVariable: 'DOCKER_PASS', usernameVariable: 'DOCKER_USER')]) {
                            sh 'echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin'
                            sh "docker build -t ${DOCKER_REGISTRY}/${APP_NAME_BACKEND}:${IMAGE_TAG} ."
                            sh "docker push ${DOCKER_REGISTRY}/${APP_NAME_BACKEND}:${IMAGE_TAG}"
                            sh "docker tag ${DOCKER_REGISTRY}/${APP_NAME_BACKEND}:${IMAGE_TAG} ${DOCKER_REGISTRY}/${APP_NAME_BACKEND}:latest"
                            sh "docker push ${DOCKER_REGISTRY}/${APP_NAME_BACKEND}:latest"
                        }
                    }
                }
            }
        }

        stage('Build & Push Frontend Image') {
            steps {
                script {
                    dir('frontend') {
                        withCredentials([usernamePassword(credentialsId: 'dockerhub-credentials', passwordVariable: 'DOCKER_PASS', usernameVariable: 'DOCKER_USER')]) {
                            sh 'echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin'
                            sh "docker build -t ${DOCKER_REGISTRY}/${APP_NAME_FRONTEND}:${IMAGE_TAG} ."
                            sh "docker push ${DOCKER_REGISTRY}/${APP_NAME_FRONTEND}:${IMAGE_TAG}"
                            sh "docker tag ${DOCKER_REGISTRY}/${APP_NAME_FRONTEND}:${IMAGE_TAG} ${DOCKER_REGISTRY}/${APP_NAME_FRONTEND}:latest"
                            sh "docker push ${DOCKER_REGISTRY}/${APP_NAME_FRONTEND}:latest"
                        }
                    }
                }
            }
        }

        stage('Deploy via Ansible') {
            steps {
                script {
                    dir('ansible') {
                        sh """
                            ansible-playbook -i inventory.ini deploy.yml \\
                                -e backend_image="${DOCKER_REGISTRY}/${APP_NAME_BACKEND}:${IMAGE_TAG}" \\
                                -e frontend_image="${DOCKER_REGISTRY}/${APP_NAME_FRONTEND}:${IMAGE_TAG}"
                        """
                    }
                }
            }
        }
    }
}
