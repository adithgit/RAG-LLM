pipeline {
    agent any

    triggers {
        githubPush()
    }

    environment {
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
                        docker.withRegistry('https://index.docker.io/v1/', 'dockerhub-credentials') {
                            def customImage = docker.build("${DOCKER_REGISTRY}/${APP_NAME_BACKEND}:${IMAGE_TAG}")
                            customImage.push()
                            customImage.push('latest')
                        }
                    }
                }
            }
        }

        stage('Build & Push Frontend Image') {
            steps {
                script {
                    dir('frontend') {
                        docker.withRegistry('https://index.docker.io/v1/', 'dockerhub-credentials') {
                            def customImage = docker.build("${DOCKER_REGISTRY}/${APP_NAME_FRONTEND}:${IMAGE_TAG}")
                            customImage.push()
                            customImage.push('latest')
                        }
                    }
                }
            }
        }

        stage('Deploy via Ansible') {
            steps {
                script {
                    dir('ansible') {
                        ansiblePlaybook(
                            playbook: 'deploy.yml',
                            inventory: 'inventory.ini',
                            extraVars: [
                                backend_image: "${DOCKER_REGISTRY}/${APP_NAME_BACKEND}:${IMAGE_TAG}",
                                frontend_image: "${DOCKER_REGISTRY}/${APP_NAME_FRONTEND}:${IMAGE_TAG}"
                            ]
                        )
                    }
                }
            }
        }
    }
}
